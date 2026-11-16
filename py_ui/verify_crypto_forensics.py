
"""Auditoria forense de criptografia: canario em disco, AEAD tamper e ciclo do cofre."""

from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

CANARY = "CANARY_SECRET_MARK_99481_X7Z"
ROOT = Path("/home/thu12/MARK-RUST")
BINARY = ROOT / "target" / "release" / "mark-vault"


SKIP_DIRS = {"node_modules", "__pycache__", ".git", "site-packages", "steamapps"}


def scan_for_canary(roots: list[Path], max_files: int = 20000) -> list[str]:
    hits: list[str] = []
    seen = 0
    for root in roots:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if seen >= max_files:
                break
            if any(part in SKIP_DIRS for part in path.parts):
                continue
            seen += 1
            if not path.is_file() or path.is_symlink():
                continue
            try:
                if path.stat().st_size > 64 * 1024 * 1024:
                    continue
                blob = path.read_bytes()
            except OSError:
                continue
            if CANARY.encode() in blob:
                hits.append(str(path))
    return hits


def vault_cycle(check) -> None:
    """Ciclo do cofre Rust: init, senha errada, senha certa, rekey, tamper."""
    tmp = Path(tempfile.mkdtemp(prefix="mark_vault_"))
    env = dict(os.environ)
    env["HOME"] = str(tmp)
    env.pop("MARK_VAULT_PATH", None)

    def run(*args: str, secrets: tuple[str, ...] = ()) -> dict:
        # O CLI le senhas por stdin (nunca por argv): este e o contrato real.
        stdin = "".join(f"{item}\n" for item in secrets)
        done = subprocess.run(
            [str(BINARY), *args], input=stdin, capture_output=True, text=True, env=env, timeout=120
        )
        out = (done.stdout or "").strip().splitlines()
        for line in reversed(out):
            if line.strip().startswith("{"):
                return json.loads(line)
        return {"ok": False, "raw": done.stdout + done.stderr, "code": done.returncode}

    init = run("init", secrets=("senhaForte123",))
    check("VAULT_INIT", init.get("ok") is True, f"init falhou: {init}")
    for name, value in (("a", "1"), ("b", "2"), ("c", CANARY)):
        res = run("set", secrets=("senhaForte123", name, value))
        check(f"VAULT_SET_{name}", res.get("ok") is True, f"set {name} falhou: {res}")

    wrong = run("list", secrets=("senhaErrada999",))
    check("VAULT_WRONG_PASSWORD_REJECTED", wrong.get("ok") is False, f"senha errada aceita: {wrong}")

    good = run("list", secrets=("senhaForte123",))
    check("VAULT_UNLOCK_RIGHT_PASSWORD", good.get("ok") is True and int(good.get("count", 0)) >= 3,
          f"list com senha certa falhou: {good}")

    vault_file = tmp / ".config" / "mark" / "vault.bin"
    check("VAULT_FILE_EXISTS", vault_file.is_file(), "vault.bin nao foi criado")
    if vault_file.is_file():
        mode = stat.S_IMODE(vault_file.stat().st_mode)
        check("VAULT_PERMISSIONS_0600", mode == 0o600, f"permissoes do cofre: {oct(mode)}")
        raw = bytearray(vault_file.read_bytes())
        if len(raw) > 80:
            # Inverte um bit no meio do arquivo (dentro do payload de um item) e
            # prova que a leitura DAQUELE item falha por autenticacao AEAD.
            raw[len(raw) // 2] ^= 0x01
            vault_file.write_bytes(bytes(raw))
            tampered = False
            for name in ("a", "b", "c"):
                # nome tambem entra por stdin: contrato do CLI.
                probe = run("get", secrets=("senhaForte123", name))
                if probe.get("ok") is False:
                    tampered = True
                    break
            check("VAULT_AEAD_REJECTS_TAMPER", tampered,
                  "bit invertido no payload nao foi detectado ao ler o item")

    # Rekey roda em um cofre LIMPO (o cofre acima esta adulterado de proposito).
    shutil.rmtree(tmp, ignore_errors=True)
    tmp = Path(tempfile.mkdtemp(prefix="mark_vault_rekey_"))
    env["HOME"] = str(tmp)
    init2 = run("init", secrets=("senhaForte123",))
    check("Rekey_INIT_CLEAN", init2.get("ok") is True, f"init limpo falhou: {init2}")
    for name in ("a", "b", "c"):
        run("set", secrets=("senhaForte123", name, f"valor-{name}"))

    rekey = run("rekey", secrets=("senhaForte123", "novaSenha456"))
    check("VAULT_REKEY", rekey.get("ok") is True, f"rekey falhou: {rekey}")
    after = run("list", secrets=("novaSenha456",))
    check("VAULT_REKEY_PRESERVES_RECORDS", after.get("ok") is True and int(after.get("count", 0)) >= 3,
          f"rekey perdeu registros: {after}")
    old = run("list", secrets=("senhaForte123",))
    check("VAULT_REKEY_INVALIDATES_OLD", old.get("ok") is False, f"senha antiga ainda abre: {old}")
    keys = run("get", secrets=("novaSenha456", "c"))
    check("VAULT_REKEY_VALUE_INTACT", str(keys.get("value", "")) == "valor-c",
          f"valor depois do rekey: {keys}")
    shutil.rmtree(tmp, ignore_errors=True)


def bridge_lock_cycle(check) -> None:
    """`lock` do bridge: depois de lock a sessao nao expoe mais as chaves."""
    sys.path.insert(0, str(ROOT / "py_ui"))
    from mark.rust_bridge import rust

    password = "senhaBridge987"
    locked_ok = False
    try:
        rust.vault_lock()
        before = rust.vault_list()
        rust.vault_unlock(password)
        rust.vault_lock()
        after = rust.vault_list()
        keys = after.get("keys") or []
        locked_ok = after.get("ok") is False or not keys
        print(f"BRIDGE_LOCK before_ok={before.get('ok')} after_ok={after.get('ok')} keys={keys}")
    except (OSError, RuntimeError, ValueError) as exc:
        locked_ok = False
        print(f"BRIDGE_LOCK erro: {exc}")
    check("VAULT_LOCK_HIDES_SESSION", locked_ok, "apos lock a listagem continuou expondo chaves")


def main() -> int:
    failures: list[str] = []

    def check(label: str, ok: bool, detail: str = "") -> None:
        print(f"{'PASS' if ok else 'FAIL'} {label}" + (f" :: {detail}" if not ok else ""))
        if not ok:
            failures.append(f"{label}: {detail}")

    sys.path.insert(0, str(ROOT / "py_ui"))
    from mark.config.llm_config import LLMKeyVault

    # ---------------------------------------- 1. canario no fluxo real de Settings
    vault = LLMKeyVault()
    vault.set_key("canary-provider", CANARY, {"origin": "forensics"})
    check("CANARY_STORED_AND_READ_BACK", vault.get_key("canary-provider") == CANARY,
          "fluxo de Settings nao devolveu a chave gravada")
    blob = vault.vault_file.read_bytes() if vault.vault_file.is_file() else b""
    check("CANARY_ABSENT_FROM_CIPHERTEXT_FILE", CANARY.encode() not in blob,
          "a chave aparece em texto puro dentro do cofre")
    mode = stat.S_IMODE(vault.vault_file.stat().st_mode) if vault.vault_file.is_file() else 0
    check("CANARY_VAULT_MODE_0600", mode == 0o600, f"permissoes: {oct(mode)}")

    hits = scan_for_canary([
        Path.home() / ".config" / "mark",
        Path.home() / ".local" / "share" / "mark",
        Path.home() / ".local" / "state" / "mark",
        Path("/tmp"),
    ])
    hits = [h for h in hits if not h.endswith("vault.bin")]
    check("CANARY_NOT_IN_PLAINTEXT_ANYWHERE", not hits, f"texto puro encontrado em: {hits[:6]}")

    # ---------------------------------- 2. adulteracao AEAD no cofre Python
    tmp = Path(tempfile.mkdtemp(prefix="mark_py_vault_"))
    try:
        iso = LLMKeyVault(vault_file=tmp / "vault.bin", master_key_file=tmp / ".master_key")
        for i in range(3):
            iso.set_key(f"p{i}", f"valor-{i}")
        check("PY_VAULT_ROUNDTRIP", all(iso.get_key(f"p{i}") == f"valor-{i}" for i in range(3)),
              "ida e volta de 3 registros falhou")
        blob = bytearray((tmp / "vault.bin").read_bytes())
        blob[-1] ^= 0x01
        (tmp / "vault.bin").write_bytes(bytes(blob))
        rejected = False
        try:
            iso.get_key("p0")
        except Exception as exc:
            rejected = "autentica" in str(exc).lower() or "StorageSecurity" in type(exc).__name__
        check("PY_VAULT_AEAD_REJECTS_TAMPER", rejected, "bit invertido passou sem erro de autenticacao")
        mkey = tmp / ".master_key"
        if mkey.is_file():
            mmode = stat.S_IMODE(mkey.stat().st_mode)
            check("PY_MASTER_KEY_MODE_0600", mmode == 0o600, f"permissoes: {oct(mmode)}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    vault.delete_key("canary-provider")

    # ------------------------------------------- 3. ciclo do cofre Rust real
    if BINARY.is_file():
        vault_cycle(check)
        bridge_lock_cycle(check)
    else:
        failures.append("mark-vault binario ausente: ciclo Rust nao executado")

    if failures:
        print(f"\nFAIL ({len(failures)} problemas)")
        for item in failures:
            print("  -", item)
        return 1
    print("\nCRYPTO FORENSICS OK: sem plaintext, AEAD rejeita adulteracao, rekey preserva registros")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
