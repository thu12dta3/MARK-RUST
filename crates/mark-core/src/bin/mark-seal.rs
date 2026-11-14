//! Empacotador selado do MARK: chunks AES-256-GCM com chave derivada por Argon2id.
//!
//! O checkpoint de origem NUNCA e alterado: leitura somente. O arquivo gerado
//! (.mkbin) nao contem header JSON safetensors nem nomes de tensores, apenas um
//! cabecalho binario curto e o fluxo cifrado com AAD por chunk.

use std::fs::{File, OpenOptions};
use std::io::{Read, Write};
use std::path::{Path, PathBuf};

use anyhow::{bail, Context, Result};
use mark_core::vault::{EncryptedRecord, MasterKey};
use sha2::{Digest, Sha256};

const MAGIC: &[u8; 4] = b"MKB1";
const CHUNK: usize = 4 * 1024 * 1024;
const SALT_LEN: usize = 16;
const M_KIB: u32 = 64 * 1024;
const T_COST: u32 = 3;
const P_COST: u32 = 4;

fn read_password() -> String {
    let mut raw = String::new();
    let _ = std::io::stdin().read_to_string(&mut raw);
    raw.lines().next().unwrap_or("").trim().to_string()
}

fn collect_sources(root: &Path) -> Result<Vec<PathBuf>> {
    let mut files = Vec::new();
    for entry in std::fs::read_dir(root).with_context(|| format!("listar {}", root.display()))? {
        let path = entry?.path();
        if path.extension().and_then(|e| e.to_str()) == Some("safetensors") {
            files.push(path);
        }
    }
    files.sort();
    if files.is_empty() {
        bail!("nenhum .safetensors em {}", root.display());
    }
    Ok(files)
}

fn cmd_pack(source: &Path, output: &Path, password: &str) -> Result<()> {
    if password.len() < 8 {
        bail!("senha do container precisa de ao menos 8 caracteres");
    }
    let files = collect_sources(source)?;
    if let Some(parent) = output.parent() {
        std::fs::create_dir_all(parent)?;
    }
    let mut salt = [0u8; SALT_LEN];
    rand_core::RngCore::fill_bytes(&mut rand_core::OsRng, &mut salt);
    let key = MasterKey::derive(password, &salt, M_KIB, T_COST, P_COST)?;
    key.lock_in_memory()?;

    // 1a passada: hash e tamanho do plaintext
    let mut hasher = Sha256::new();
    let mut total: u64 = 0;
    for path in &files {
        let mut file = File::open(path)?;
        let mut buffer = vec![0u8; CHUNK];
        loop {
            let read = file.read(&mut buffer)?;
            if read == 0 {
                break;
            }
            hasher.update(&buffer[..read]);
            total += read as u64;
        }
    }
    let source_hash: [u8; 32] = hasher.finalize().into();

    let mut out = OpenOptions::new().create(true).write(true).truncate(true).open(output)?;
    out.write_all(MAGIC)?;
    out.write_all(&1u16.to_le_bytes())?;
    out.write_all(&(CHUNK as u32).to_le_bytes())?;
    out.write_all(&salt)?;
    out.write_all(&M_KIB.to_le_bytes())?;
    out.write_all(&T_COST.to_le_bytes())?;
    out.write_all(&P_COST.to_le_bytes())?;
    out.write_all(&total.to_le_bytes())?;
    out.write_all(&source_hash)?;
    // Cada arquivo e fatiado em chunks proprios (um chunk nunca atravessa dois
    // arquivos), portanto o total de chunks e a soma dos ceils por arquivo.
    let mut chunk_count: u64 = 0;
    for path in &files {
        let len = std::fs::metadata(path)?.len();
        chunk_count += len.div_ceil(CHUNK as u64);
    }
    out.write_all(&chunk_count.to_le_bytes())?;

    let mut index: u64 = 0;
    let mut offset: u64 = 0;
    for path in &files {
        let mut file = File::open(path)?;
        let mut buffer = vec![0u8; CHUNK];
        loop {
            let mut filled = 0usize;
            while filled < CHUNK {
                let read = file.read(&mut buffer[filled..])?;
                if read == 0 {
                    break;
                }
                filled += read;
            }
            if filled == 0 {
                break;
            }
            let mut aad = Vec::with_capacity(20);
            aad.extend_from_slice(&index.to_le_bytes());
            aad.extend_from_slice(&offset.to_le_bytes());
            aad.extend_from_slice(&(filled as u32).to_le_bytes());
            let record = EncryptedRecord::seal(&key, &aad, &buffer[..filled])?;
            let raw = record.to_bytes();
            out.write_all(&(filled as u32).to_le_bytes())?;
            out.write_all(&(raw.len() as u32).to_le_bytes())?;
            out.write_all(&raw)?;
            index += 1;
            offset += filled as u64;
        }
    }
    out.flush()?;
    out.sync_all()?;
    key.unlock_memory().ok();
    println!(
        "{{\"ok\":true,\"mode\":\"pack\",\"file\":\"{}\",\"source\":\"{}\",\"files\":{},\"plain_bytes\":{},\"chunks\":{},\"sha256\":\"{}\"}}",
        output.display(),
        source.display(),
        files.len(),
        total,
        chunk_count,
        hex(&source_hash)
    );
    Ok(())
}

fn hex(bytes: &[u8]) -> String {
    bytes.iter().map(|b| format!("{b:02x}")).collect()
}

#[allow(clippy::type_complexity)]
fn read_header(
    file: &mut File,
) -> Result<(u32, [u8; SALT_LEN], u32, u32, u32, u64, [u8; 32], u64)> {
    let mut magic = [0u8; 4];
    file.read_exact(&mut magic)?;
    if &magic != MAGIC {
        bail!("magic invalido: nao e um container .mkbin");
    }
    let mut version = [0u8; 2];
    file.read_exact(&mut version)?;
    let mut chunk = [0u8; 4];
    file.read_exact(&mut chunk)?;
    let chunk_size = u32::from_le_bytes(chunk);
    let mut salt = [0u8; SALT_LEN];
    file.read_exact(&mut salt)?;
    let mut params = [0u8; 4];
    file.read_exact(&mut params)?;
    let m_kib = u32::from_le_bytes(params);
    file.read_exact(&mut params)?;
    let t_cost = u32::from_le_bytes(params);
    file.read_exact(&mut params)?;
    let p_cost = u32::from_le_bytes(params);
    let mut total = [0u8; 8];
    file.read_exact(&mut total)?;
    let mut hash = [0u8; 32];
    file.read_exact(&mut hash)?;
    let mut count = [0u8; 8];
    file.read_exact(&mut count)?;
    Ok((
        chunk_size,
        salt,
        m_kib,
        t_cost,
        p_cost,
        u64::from_le_bytes(total),
        hash,
        u64::from_le_bytes(count),
    ))
}

fn cmd_verify(path: &Path, password: &str) -> Result<()> {
    let mut file = File::open(path)?;
    let (_chunk_size, salt, m_kib, t_cost, p_cost, total, expected, count) = read_header(&mut file)?;
    let key = MasterKey::derive(password, &salt, m_kib, t_cost, p_cost)?;
    key.lock_in_memory()?;
    let mut hasher = Sha256::new();
    let mut index: u64 = 0;
    let mut offset: u64 = 0;
    while index < count {
        let mut plain_buf = [0u8; 4];
        file.read_exact(&mut plain_buf)?;
        let plain_len = u32::from_le_bytes(plain_buf);
        let mut len_buf = [0u8; 4];
        file.read_exact(&mut len_buf)?;
        let len = u32::from_le_bytes(len_buf) as usize;
        let mut raw = vec![0u8; len];
        file.read_exact(&mut raw)?;
        let record = EncryptedRecord::from_bytes(&raw)?;
        let mut aad = Vec::with_capacity(20);
        aad.extend_from_slice(&index.to_le_bytes());
        aad.extend_from_slice(&offset.to_le_bytes());
        aad.extend_from_slice(&plain_len.to_le_bytes());
        let mut plain = record.open(&key, &aad)?;
        if plain.is_empty() || plain.len() != plain_len as usize {
            bail!("chunk {index} com tamanho inesperado");
        }
        hasher.update(&plain);
        offset += plain.len() as u64;
        zeroize::Zeroize::zeroize(&mut plain);
        index += 1;
    }
    let computed: [u8; 32] = hasher.finalize().into();
    key.unlock_memory().ok();
    let ok = computed == expected && offset == total;
    println!(
        "{{\"ok\":{},\"mode\":\"verify\",\"file\":\"{}\",\"chunks\":{},\"plain_bytes\":{},\"sha256\":\"{}\",\"hash_match\":{}}}",
        ok,
        path.display(),
        count,
        offset,
        hex(&computed),
        computed == expected
    );
    if !ok {
        bail!("verificacao falhou: hash ou tamanho divergente");
    }
    Ok(())
}

fn main() -> Result<()> {
    let args: Vec<String> = std::env::args().skip(1).collect();
    let mode = args.first().cloned().unwrap_or_default();
    let password = read_password();
    match mode.as_str() {
        "pack" => {
            let source = PathBuf::from(args.get(1).context("uso: pack <dir> <out.mkbin>")?);
            let output = PathBuf::from(args.get(2).context("uso: pack <dir> <out.mkbin>")?);
            cmd_pack(&source, &output, &password)
        }
        "verify" => {
            let path = PathBuf::from(args.get(1).context("uso: verify <file.mkbin>")?);
            cmd_verify(&path, &password)
        }
        other => bail!("comando desconhecido: {other} (use pack|verify)"),
    }
}
