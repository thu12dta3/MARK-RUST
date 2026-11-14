//! Backend GPU PTX `sm_75` para o motor SVID 1-Bit.
//!
//! Carrega `libcuda.so.1` em runtime via `dlopen`, compila os kernels PTX com
//! `cuModuleLoadData` e executa matvec int8/int4 e W1A4 na GPU. Se `cuInit`
//! falhar, `GpuEngine::create` devolve erro e o chamador usa o caminho CPU.

use std::ffi::c_void;
use std::ptr;
use std::sync::OnceLock;

use anyhow::{bail, Context, Result};

const PTX_WARP: &str = include_str!("../ptx/warp_sm75.ptx");
const PTX_W1A4: &str = include_str!("../ptx/w1a4_sm75.ptx");

type CuInitFn = unsafe extern "C" fn(u32) -> i32;
type CuDeviceGetFn = unsafe extern "C" fn(*mut i32, i32) -> i32;
type CuDeviceGetNameFn = unsafe extern "C" fn(*mut i8, i32, i32) -> i32;
type CuDevicePrimaryCtxRetainFn = unsafe extern "C" fn(*mut *mut c_void, i32) -> i32;
type CuCtxSetCurrentFn = unsafe extern "C" fn(*mut c_void) -> i32;
type CuModuleLoadDataFn = unsafe extern "C" fn(*mut *mut c_void, *const c_void) -> i32;
type CuModuleGetFunctionFn = unsafe extern "C" fn(*mut *mut c_void, *mut c_void, *const u8) -> i32;
type CuMemAllocV2Fn = unsafe extern "C" fn(*mut u64, usize) -> i32;
type CuMemFreeV2Fn = unsafe extern "C" fn(u64) -> i32;
type CuMemcpyHtoDV2Fn = unsafe extern "C" fn(u64, *const c_void, usize) -> i32;
type CuMemcpyDtoHV2Fn = unsafe extern "C" fn(*mut c_void, u64, usize) -> i32;
type CuMemsetD8Fn = unsafe extern "C" fn(u64, u8, usize) -> i32;
type CuLaunchKernelFn = unsafe extern "C" fn(
    *mut c_void,
    u32,
    u32,
    u32,
    u32,
    u32,
    u32,
    u32,
    *mut c_void,
    *mut *mut c_void,
    *mut *mut c_void,
) -> i32;
type CuCtxSynchronizeFn = unsafe extern "C" fn() -> i32;

#[link(name = "dl")]
extern "C" {
    fn dlopen(filename: *const u8, flag: i32) -> *mut c_void;
    fn dlsym(handle: *mut c_void, symbol: *const u8) -> *mut c_void;
}

const RTLD_LAZY: i32 = 1;

struct Driver {
    ctx: usize,
    f_i8: usize,
    f_gus: usize,
    f_daw: usize,
    f_swiglu: usize,
    f_w1a4: usize,
    set_ctx: CuCtxSetCurrentFn,
    alloc: CuMemAllocV2Fn,
    free: CuMemFreeV2Fn,
    htod: CuMemcpyHtoDV2Fn,
    dtoh: CuMemcpyDtoHV2Fn,
    memset8: CuMemsetD8Fn,
    launch: CuLaunchKernelFn,
    sync: CuCtxSynchronizeFn,
}

unsafe impl Send for Driver {}
unsafe impl Sync for Driver {}

static DRIVER: OnceLock<Option<Driver>> = OnceLock::new();

fn load_symbol(handle: *mut c_void, name: &[u8]) -> Option<*mut c_void> {
    let p = unsafe { dlsym(handle, name.as_ptr()) };
    if p.is_null() {
        None
    } else {
        Some(p)
    }
}

macro_rules! sym {
    ($handle:expr, $name:literal, $t:ty) => {{
        let p = load_symbol($handle, concat!($name, "\0").as_bytes())?;
        std::mem::transmute::<*mut c_void, $t>(p)
    }};
}

unsafe fn load_module(handle: *mut c_void, ptx: &str) -> Option<(usize, usize, usize, usize, usize)> {
    let cu_mod_load: CuModuleLoadDataFn = sym!(handle, "cuModuleLoadData", CuModuleLoadDataFn);
    let cu_mod_func: CuModuleGetFunctionFn = sym!(handle, "cuModuleGetFunction", CuModuleGetFunctionFn);
    let mut ptx_z: Vec<u8> = Vec::with_capacity(ptx.len() + 1);
    ptx_z.extend_from_slice(ptx.as_bytes());
    ptx_z.push(0);
    let mut module: *mut c_void = ptr::null_mut();
    unsafe {
        if cu_mod_load(&mut module, ptx_z.as_ptr() as *const c_void) != 0 || module.is_null() {
            return None;
        }
    }
    let mut fns = [0usize; 5];
    for (i, name) in [
        "rust_gpu_int8_matvec_warp",
        "rust_gpu_int4_gate_up_swiglu_warp",
        "rust_gpu_int4_down_axpy_warp",
        "rust_gpu_swiglu_vec",
        "rust_gpu_1bit_w1a4_matvec",
    ]
    .iter()
    .enumerate()
    {
        let mut f: *mut c_void = ptr::null_mut();
        let cname = format!("{name}\0");
        let rc = unsafe { cu_mod_func(&mut f, module, cname.as_ptr()) };
        if rc == 0 && !f.is_null() {
            fns[i] = f as usize;
        }
    }
    Some((fns[0], fns[1], fns[2], fns[3], fns[4]))
}

fn init_driver() -> Option<Driver> {
    unsafe {
        let mut handle = ptr::null_mut();
        for name in [b"libcuda.so.1\0".as_slice(), b"libcuda.so\0".as_slice()] {
            handle = dlopen(name.as_ptr(), RTLD_LAZY);
            if !handle.is_null() {
                break;
            }
        }
        if handle.is_null() {
            return None;
        }
        let cu_init: CuInitFn = sym!(handle, "cuInit", CuInitFn);
        let cu_dev_get: CuDeviceGetFn = sym!(handle, "cuDeviceGet", CuDeviceGetFn);
        let cu_ctx_retain: CuDevicePrimaryCtxRetainFn =
            sym!(handle, "cuDevicePrimaryCtxRetain", CuDevicePrimaryCtxRetainFn);
        let set_ctx: CuCtxSetCurrentFn = sym!(handle, "cuCtxSetCurrent", CuCtxSetCurrentFn);
        let alloc: CuMemAllocV2Fn = sym!(handle, "cuMemAlloc_v2", CuMemAllocV2Fn);
        let free: CuMemFreeV2Fn = sym!(handle, "cuMemFree_v2", CuMemFreeV2Fn);
        let htod: CuMemcpyHtoDV2Fn = sym!(handle, "cuMemcpyHtoD_v2", CuMemcpyHtoDV2Fn);
        let dtoh: CuMemcpyDtoHV2Fn = sym!(handle, "cuMemcpyDtoH_v2", CuMemcpyDtoHV2Fn);
        let memset8: CuMemsetD8Fn = sym!(handle, "cuMemsetD8", CuMemsetD8Fn);
        let launch: CuLaunchKernelFn = sym!(handle, "cuLaunchKernel", CuLaunchKernelFn);
        let sync: CuCtxSynchronizeFn = sym!(handle, "cuCtxSynchronize", CuCtxSynchronizeFn);

        if cu_init(0) != 0 {
            return None;
        }
        let mut dev: i32 = 0;
        if cu_dev_get(&mut dev, 0) != 0 {
            return None;
        }
        let mut ctx: *mut c_void = ptr::null_mut();
        if cu_ctx_retain(&mut ctx, dev) != 0 || ctx.is_null() {
            return None;
        }
        if set_ctx(ctx) != 0 {
            return None;
        }
        let (f_i8, f_gus, f_daw, f_swiglu, _) = load_module(handle, PTX_WARP)?;
        if f_i8 == 0 || f_gus == 0 || f_daw == 0 || f_swiglu == 0 {
            return None;
        }
        let (_, _, _, _, w) = load_module(handle, PTX_W1A4)?;
        if w == 0 {
            return None;
        }
        Some(Driver {
            ctx: ctx as usize,
            f_i8,
            f_gus,
            f_daw,
            f_swiglu,
            f_w1a4: w,
            set_ctx,
            alloc,
            free,
            htod,
            dtoh,
            memset8,
            launch,
            sync,
        })
    }
}

fn driver() -> Option<&'static Driver> {
    DRIVER.get_or_init(init_driver).as_ref()
}

/// Indica se o driver CUDA e os kernels PTX `sm_75` estao operacionais.
pub fn gpu_available() -> bool {
    driver().is_some()
}

/// Nome do dispositivo CUDA, quando disponivel.
pub fn device_name() -> Option<String> {
    unsafe {
        let mut handle = ptr::null_mut();
        for name in [b"libcuda.so.1\0".as_slice(), b"libcuda.so\0".as_slice()] {
            handle = dlopen(name.as_ptr(), RTLD_LAZY);
            if !handle.is_null() {
                break;
            }
        }
        if handle.is_null() {
            return None;
        }
        let cu_init: CuInitFn = sym!(handle, "cuInit", CuInitFn);
        let cu_dev_get: CuDeviceGetFn = sym!(handle, "cuDeviceGet", CuDeviceGetFn);
        let cu_name: CuDeviceGetNameFn = sym!(handle, "cuDeviceGetName", CuDeviceGetNameFn);
        if cu_init(0) != 0 {
            return None;
        }
        let mut dev: i32 = 0;
        if cu_dev_get(&mut dev, 0) != 0 {
            return None;
        }
        let mut buf = [0i8; 128];
        if cu_name(buf.as_mut_ptr(), 128, dev) != 0 {
            return None;
        }
        let bytes: Vec<u8> = buf.iter().take_while(|c| **c != 0).map(|c| *c as u8).collect();
        Some(String::from_utf8_lossy(&bytes).into_owned())
    }
}


type CuMemGetInfoFn = unsafe extern "C" fn(*mut usize, *mut usize) -> i32;
type CuDeviceGetAttributeFn = unsafe extern "C" fn(*mut i32, i32, i32) -> i32;

fn cuda_handle() -> *mut c_void {
    unsafe {
        for name in [b"libcuda.so.1\0".as_slice(), b"libcuda.so\0".as_slice()] {
            let handle = dlopen(name.as_ptr(), RTLD_LAZY);
            if !handle.is_null() {
                return handle;
            }
        }
        ptr::null_mut()
    }
}

/// VRAM total do dispositivo 0 em MiB, lida do driver CUDA.
pub fn device_memory_mib() -> Option<u64> {
    unsafe {
        let handle = cuda_handle();
        if handle.is_null() {
            return None;
        }
        let cu_init: CuInitFn = sym!(handle, "cuInit", CuInitFn);
        if cu_init(0) != 0 {
            return None;
        }
        let mut get_info: CuMemGetInfoFn = sym!(handle, "cuMemGetInfo_v2", CuMemGetInfoFn);
        if get_info as usize == 0 {
            get_info = sym!(handle, "cuMemGetInfo", CuMemGetInfoFn);
        }
        if get_info as usize == 0 {
            return None;
        }
        let mut free: usize = 0;
        let mut total: usize = 0;
        if get_info(&mut free, &mut total) != 0 || total == 0 {
            return None;
        }
        Some((total / (1024 * 1024)) as u64)
    }
}

/// Compute capability (major, minor) do dispositivo 0.
pub fn compute_capability() -> Option<(i32, i32)> {
    unsafe {
        let handle = cuda_handle();
        if handle.is_null() {
            return None;
        }
        let cu_init: CuInitFn = sym!(handle, "cuInit", CuInitFn);
        let cu_dev_get: CuDeviceGetFn = sym!(handle, "cuDeviceGet", CuDeviceGetFn);
        let cu_attr: CuDeviceGetAttributeFn = sym!(handle, "cuDeviceGetAttribute", CuDeviceGetAttributeFn);
        if cu_init(0) != 0 || cu_attr as usize == 0 {
            return None;
        }
        let mut dev: i32 = 0;
        if cu_dev_get(&mut dev, 0) != 0 {
            return None;
        }
        let mut major: i32 = 0;
        let mut minor: i32 = 0;
        if cu_attr(&mut major, 75, dev) != 0 || cu_attr(&mut minor, 76, dev) != 0 {
            return None;
        }
        Some((major, minor))
    }
}

/// Buffer alocado na VRAM, liberado no `Drop`.
pub struct GpuBuffer {
    ptr: u64,
    len: usize,
}

impl GpuBuffer {
    /// Endereco do dispositivo.
    pub fn ptr(&self) -> u64 {
        self.ptr
    }

    /// Tamanho em bytes.
    pub fn len(&self) -> usize {
        self.len
    }

    /// Indica buffer vazio.
    pub fn is_empty(&self) -> bool {
        self.len == 0
    }
}

impl Drop for GpuBuffer {
    fn drop(&mut self) {
        if let Some(d) = driver() {
            if self.ptr != 0 {
                unsafe {
                    (d.set_ctx)(d.ctx as *mut c_void);
                    (d.free)(self.ptr);
                }
            }
        }
        self.ptr = 0;
    }
}

/// Motores CUDA carregados, com buffers temporarios reutilizados.
pub struct GpuEngine {
    d: &'static Driver,
    d_x: GpuBuffer,
    d_y: GpuBuffer,
    d_inter: GpuBuffer,
    d_accum: GpuBuffer,
    d_planes: GpuBuffer,
    d_mblk: GpuBuffer,
}

impl GpuEngine {
    /// Cria o motor; falha quando `cuInit` ou os kernels PTX nao carregam.
    pub fn create() -> Result<Self> {
        let d = driver().context("driver CUDA indisponivel (nvidia-smi/cuInit)")?;
        unsafe {
            if (d.set_ctx)(d.ctx as *mut c_void) != 0 {
                bail!("cuCtxSetCurrent falhou");
            }
        }
        let alloc = |bytes: usize| -> Result<GpuBuffer> {
            let mut p: u64 = 0;
            let rc = unsafe { (d.alloc)(&mut p, bytes) };
            if rc != 0 || p == 0 {
                bail!("cuMemAlloc de {bytes} bytes falhou (codigo {rc})");
            }
            Ok(GpuBuffer { ptr: p, len: bytes })
        };
        let engine = Self {
            d,
            d_x: alloc(16_384 * 4)?,
            d_y: alloc(102_400 * 4)?,
            d_inter: alloc(16_384 * 4)?,
            d_accum: alloc(2_048 * 4)?,
            d_planes: alloc(64 * 4 * 8)?,
            d_mblk: alloc(64 * 4)?,
        };
        unsafe {
            (d.sync)();
        }
        Ok(engine)
    }

    fn alloc_bytes(&self, bytes: usize) -> Result<GpuBuffer> {
        let mut p: u64 = 0;
        let rc = unsafe { (self.d.alloc)(&mut p, bytes.max(1)) };
        if rc != 0 || p == 0 {
            bail!("cuMemAlloc de {bytes} bytes falhou (codigo {rc})");
        }
        Ok(GpuBuffer { ptr: p, len: bytes })
    }

    fn upload(&self, bytes: &[u8]) -> Result<GpuBuffer> {
        let buf = self.alloc_bytes(bytes.len())?;
        let rc = unsafe {
            (self.d.htod)(
                buf.ptr,
                bytes.as_ptr() as *const c_void,
                bytes.len(),
            )
        };
        if rc != 0 {
            bail!("cuMemcpyHtoD falhou (codigo {rc})");
        }
        Ok(buf)
    }

    /// Envia int8.
    pub fn upload_i8(&self, data: &[i8]) -> Result<GpuBuffer> {
        let bytes = unsafe { std::slice::from_raw_parts(data.as_ptr() as *const u8, data.len()) };
        self.upload(bytes)
    }

    /// Envia u8.
    pub fn upload_u8(&self, data: &[u8]) -> Result<GpuBuffer> {
        self.upload(data)
    }

    /// Envia f32.
    pub fn upload_f32(&self, data: &[f32]) -> Result<GpuBuffer> {
        let bytes = unsafe { std::slice::from_raw_parts(data.as_ptr() as *const u8, data.len() * 4) };
        self.upload(bytes)
    }

    /// Envia u64.
    pub fn upload_u64(&self, data: &[u64]) -> Result<GpuBuffer> {
        let bytes = unsafe { std::slice::from_raw_parts(data.as_ptr() as *const u8, data.len() * 8) };
        self.upload(bytes)
    }

    /// Envia um vetor f32 para um buffer existente.
    pub fn htod_f32(&self, dst: &GpuBuffer, data: &[f32]) -> Result<()> {
        let bytes = unsafe { std::slice::from_raw_parts(data.as_ptr() as *const u8, data.len() * 4) };
        let rc = unsafe {
            (self.d.htod)(dst.ptr, bytes.as_ptr() as *const c_void, bytes.len())
        };
        if rc != 0 {
            bail!("cuMemcpyHtoD falhou (codigo {rc})");
        }
        Ok(())
    }

    fn dtoh_f32(&self, src: &GpuBuffer, out: &mut [f32]) -> Result<()> {
        let bytes = unsafe {
            std::slice::from_raw_parts_mut(out.as_mut_ptr() as *mut u8, out.len() * 4)
        };
        let rc = unsafe {
            (self.d.dtoh)(bytes.as_mut_ptr() as *mut c_void, src.ptr, bytes.len())
        };
        if rc != 0 {
            bail!("cuMemcpyDtoH falhou (codigo {rc})");
        }
        Ok(())
    }

    #[allow(clippy::too_many_arguments)]
    fn launch_i8_raw(
        &self,
        w: &GpuBuffer,
        sc: &GpuBuffer,
        d_in: &GpuBuffer,
        d_out: &GpuBuffer,
        d_mask: u64,
        m_rows: usize,
        k_cols: usize,
    ) {
        let mut p_w = w.ptr;
        let mut p_sc = sc.ptr;
        let mut p_x = d_in.ptr;
        let mut p_out = d_out.ptr;
        let mut p_mask = d_mask;
        let mut p_k = k_cols as u32;
        let mut p_m = m_rows as u32;
        let mut params: [*mut c_void; 7] = [
            &mut p_w as *mut u64 as *mut c_void,
            &mut p_sc as *mut u64 as *mut c_void,
            &mut p_x as *mut u64 as *mut c_void,
            &mut p_out as *mut u64 as *mut c_void,
            &mut p_mask as *mut u64 as *mut c_void,
            &mut p_k as *mut u32 as *mut c_void,
            &mut p_m as *mut u32 as *mut c_void,
        ];
        unsafe {
            (self.d.launch)(
                self.d.f_i8 as *mut c_void,
                (m_rows as u32).div_ceil(4),
                1,
                1,
                128,
                1,
                1,
                0,
                ptr::null_mut(),
                params.as_mut_ptr(),
                ptr::null_mut(),
            );
        }
    }

    /// Multiplicacao matriz-vetor int8 com mascara opcional (LM head).
    #[allow(clippy::too_many_arguments)]
    pub fn matvec_i8(
        &self,
        x: &[f32],
        w: &GpuBuffer,
        sc: &GpuBuffer,
        mask: Option<&GpuBuffer>,
        m_rows: usize,
        k_cols: usize,
        out: &mut [f32],
    ) -> Result<()> {
        if x.len() < k_cols {
            bail!("matvec_i8: entrada com {} valores, esperado {k_cols}", x.len());
        }
        if out.len() < m_rows {
            bail!("matvec_i8: saida com {} valores, esperado {m_rows}", out.len());
        }
        self.htod_f32(&self.d_x, &x[..k_cols])?;
        let mask_ptr = mask.map(|m| m.ptr).unwrap_or(0);
        self.launch_i8_raw(w, sc, &self.d_x, &self.d_y, mask_ptr, m_rows, k_cols);
        self.dtoh_f32(&self.d_y, &mut out[..m_rows])?;
        Ok(())
    }

    /// Projecoes q e kv_a em uma unica submissao.
    #[allow(clippy::too_many_arguments)]
    #[allow(clippy::too_many_arguments)]
    pub fn matvec_q_kva(
        &self,
        x: &[f32],
        q_w: &GpuBuffer,
        q_sc: &GpuBuffer,
        kva_w: &GpuBuffer,
        kva_sc: &GpuBuffer,
        q_out: &mut [f32],
        kva_out: &mut [f32],
    ) -> Result<()> {
        self.htod_f32(&self.d_x, &x[..2048])?;
        self.launch_i8_raw(q_w, q_sc, &self.d_x, &self.d_y, 0, 3072, 2048);
        self.launch_i8_raw(kva_w, kva_sc, &self.d_x, &self.d_inter, 0, 576, 2048);
        self.dtoh_f32(&self.d_y, &mut q_out[..3072])?;
        self.dtoh_f32(&self.d_inter, &mut kva_out[..576])?;
        Ok(())
    }

    /// MLP compartilhada: gate/up na GPU, SwiGLU na GPU, down acumulando em `d_accum`.
    #[allow(clippy::too_many_arguments)]
    pub fn shared_mlp(
        &self,
        x: &[f32],
        g_w: &GpuBuffer,
        g_sc: &GpuBuffer,
        u_w: &GpuBuffer,
        u_sc: &GpuBuffer,
        d_w: &GpuBuffer,
        d_sc: &GpuBuffer,
        inter: usize,
    ) -> Result<()> {
        self.htod_f32(&self.d_x, &x[..2048])?;
        self.launch_i8_raw(g_w, g_sc, &self.d_x, &self.d_y, 0, inter, 2048);
        self.launch_i8_raw(u_w, u_sc, &self.d_x, &self.d_inter, 0, inter, 2048);
        let (mut pg, mut pu, mut pn) = (self.d_y.ptr, self.d_inter.ptr, inter as u32);
        let mut params: [*mut c_void; 3] = [
            &mut pg as *mut u64 as *mut c_void,
            &mut pu as *mut u64 as *mut c_void,
            &mut pn as *mut u32 as *mut c_void,
        ];
        unsafe {
            (self.d.launch)(
                self.d.f_swiglu as *mut c_void,
                (inter as u32).div_ceil(128),
                1,
                1,
                128,
                1,
                1,
                0,
                ptr::null_mut(),
                params.as_mut_ptr(),
                ptr::null_mut(),
            );
        }
        self.launch_i8_raw(d_w, d_sc, &self.d_y, &self.d_accum, 0, 2048, inter);
        Ok(())
    }

    /// Busca o resultado acumulado da MLP compartilhada.
    pub fn fetch_shared(&self, out: &mut [f32]) -> Result<()> {
        self.dtoh_f32(&self.d_accum, &mut out[..2048])
    }

    /// Executa um expert int4 sobre a ativacao, somando `weight` no acumulador.
    #[allow(clippy::too_many_arguments)]
    pub fn moe_add_expert(
        &self,
        x: &[f32],
        ex: &GpuExperts,
        expert: usize,
        weight: f32,
        inter: usize,
        hidden: usize,
    ) -> Result<()> {
        self.htod_f32(&self.d_x, &x[..hidden])?;
        let g_q = ex.gate_q4.ptr + (expert * inter * 1024) as u64;
        let g_s = ex.gate_sc.ptr + (expert * inter * 16 * 4) as u64;
        let u_q = ex.up_q4.ptr + (expert * inter * 1024) as u64;
        let u_s = ex.up_sc.ptr + (expert * inter * 16 * 4) as u64;
        let (mut pgq, mut pgs, mut puq, mut pus, mut px, mut pout, mut pm) = (
            g_q,
            g_s,
            u_q,
            u_s,
            self.d_x.ptr,
            self.d_y.ptr,
            inter as u32,
        );
        let mut gus: [*mut c_void; 7] = [
            &mut pgq as *mut u64 as *mut c_void,
            &mut pgs as *mut u64 as *mut c_void,
            &mut puq as *mut u64 as *mut c_void,
            &mut pus as *mut u64 as *mut c_void,
            &mut px as *mut u64 as *mut c_void,
            &mut pout as *mut u64 as *mut c_void,
            &mut pm as *mut u32 as *mut c_void,
        ];
        unsafe {
            (self.d.launch)(
                self.d.f_gus as *mut c_void,
                (inter as u32) / 4,
                1,
                1,
                128,
                1,
                1,
                0,
                ptr::null_mut(),
                gus.as_mut_ptr(),
                ptr::null_mut(),
            );
        }
        let d_q = ex.down_q4.ptr + (expert * hidden * 704) as u64;
        let d_s = ex.down_sc.ptr + (expert * hidden * 11 * 4) as u64;
        let (mut pdq, mut pds, mut pin, mut pacc, mut pwk, mut pdm) = (
            d_q,
            d_s,
            self.d_y.ptr,
            self.d_accum.ptr,
            weight,
            hidden as u32,
        );
        let mut daw: [*mut c_void; 6] = [
            &mut pdq as *mut u64 as *mut c_void,
            &mut pds as *mut u64 as *mut c_void,
            &mut pin as *mut u64 as *mut c_void,
            &mut pacc as *mut u64 as *mut c_void,
            &mut pwk as *mut f32 as *mut c_void,
            &mut pdm as *mut u32 as *mut c_void,
        ];
        unsafe {
            (self.d.launch)(
                self.d.f_daw as *mut c_void,
                (hidden as u32) / 4,
                1,
                1,
                128,
                1,
                1,
                0,
                ptr::null_mut(),
                daw.as_mut_ptr(),
                ptr::null_mut(),
            );
        }
        Ok(())
    }

    /// Camada linear W1A4 (LRD 1-bit) na GPU.
    #[allow(clippy::too_many_arguments)]
    pub fn lrd_w1a4(
        &self,
        x: &[f32],
        col_scale: &[f32],
        packed: &GpuBuffer,
        row_scale: &GpuBuffer,
        m_rows: usize,
        out: &mut [f32],
    ) -> Result<()> {
        let in_dim = col_scale.len();
        if in_dim % 64 != 0 {
            bail!("lrd: dimensao de entrada precisa ser multiplo de 64");
        }
        let n_blocks = in_dim / 64;
        let mut x_buf = vec![0.0f32; in_dim];
        for i in 0..x.len().min(in_dim) {
            x_buf[i] = x[i] * col_scale[i];
        }
        crate::kernels::fwht64_slice_inplace(&mut x_buf);
        let mut m_blks = Vec::with_capacity(n_blocks);
        let mut planes = Vec::with_capacity(n_blocks * 4);
        for b in 0..n_blocks {
            let (mb, pl) = crate::kernels::w1a4_pack_block64(&x_buf[b * 64..(b + 1) * 64]);
            m_blks.push(mb);
            planes.extend_from_slice(&pl);
        }
        let planes_bytes = unsafe {
            std::slice::from_raw_parts(planes.as_ptr() as *const u8, planes.len() * 8)
        };
        let rc = unsafe {
            (self.d.htod)(
                self.d_planes.ptr,
                planes_bytes.as_ptr() as *const c_void,
                planes_bytes.len(),
            )
        };
        if rc != 0 {
            bail!("cuMemcpyHtoD das ativacoes W1A4 falhou");
        }
        let mb_bytes =
            unsafe { std::slice::from_raw_parts(m_blks.as_ptr() as *const u8, m_blks.len() * 4) };
        let rc = unsafe {
            (self.d.htod)(
                self.d_mblk.ptr,
                mb_bytes.as_ptr() as *const c_void,
                mb_bytes.len(),
            )
        };
        if rc != 0 {
            bail!("cuMemcpyHtoD das escalas W1A4 falhou");
        }

        let (mut p_w, mut p_x, mut p_mb, mut p_rs, mut p_out) = (
            packed.ptr,
            self.d_planes.ptr,
            self.d_mblk.ptr,
            row_scale.ptr,
            self.d_y.ptr,
        );
        let mut p_nb = n_blocks as u32;
        let mut p_mr = m_rows as u32;
        let mut params: [*mut c_void; 7] = [
            &mut p_w as *mut u64 as *mut c_void,
            &mut p_x as *mut u64 as *mut c_void,
            &mut p_mb as *mut u64 as *mut c_void,
            &mut p_rs as *mut u64 as *mut c_void,
            &mut p_out as *mut u64 as *mut c_void,
            &mut p_nb as *mut u32 as *mut c_void,
            &mut p_mr as *mut u32 as *mut c_void,
        ];
        unsafe {
            (self.d.launch)(
                self.d.f_w1a4 as *mut c_void,
                (m_rows as u32).div_ceil(128),
                1,
                1,
                128,
                1,
                1,
                0,
                ptr::null_mut(),
                params.as_mut_ptr(),
                ptr::null_mut(),
            );
        }
        let take = m_rows.min(2048);
        self.dtoh_f32(&self.d_y, &mut out[..take])?;
        Ok(())
    }

    /// Sincroniza o contexto CUDA.
    pub fn sync(&self) {
        unsafe {
            (self.d.sync)();
        }
    }

    /// Zera bytes de um buffer (usado antes de acumulacoes).
    pub fn zero(&self, buf: &GpuBuffer) -> Result<()> {
        let rc = unsafe { (self.d.memset8)(buf.ptr, 0, buf.len()) };
        if rc != 0 {
            bail!("cuMemsetD8 falhou (codigo {rc})");
        }
        Ok(())
    }
}

/// Buffers int4 de um conjunto de experts roteados.
pub struct GpuExperts {
    pub gate_q4: GpuBuffer,
    pub gate_sc: GpuBuffer,
    pub up_q4: GpuBuffer,
    pub up_sc: GpuBuffer,
    pub down_q4: GpuBuffer,
    pub down_sc: GpuBuffer,
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn gpu_probe_reports_availability() {
        match GpuEngine::create() {
            Ok(engine) => {
                let name = device_name().unwrap_or_else(|| "CUDA".into());
                eprintln!("GPU ativa: {name}");
                let x = vec![0.25f32; 2048];
                let w = engine.upload_i8(&vec![1i8; 2048 * 4]).unwrap();
                let sc = engine.upload_f32(&[0.5f32; 4]).unwrap();
                let mut out = vec![0.0f32; 4];
                engine.matvec_i8(&x, &w, &sc, None, 4, 2048, &mut out).unwrap();
                engine.sync();
                assert!(out.iter().all(|v| v.is_finite()));
                assert!(out.iter().any(|v| v.abs() > 0.0), "saida zerada: {out:?}");
            }
            Err(e) => {
                eprintln!("GPU indisponivel, fallback CPU esperado: {e}");
            }
        }
    }
}
