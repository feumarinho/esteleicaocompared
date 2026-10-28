"""
Gera pacote_servidor.zip com tudo o que o servidor precisa para rodar o painel:
código, requirements, scripts de instalação e SÓ os dados processados (.parquet).
Os zips grandes do TSE ficam de fora.

    python deploy/empacotar.py
"""
import zipfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
SAIDA = RAIZ / "pacote_servidor.zip"

PACOTES_DE_CODIGO = ["analise", "coleta", "app"]   # pastas de código (a pasta app/ surge na reorganização do painel)
arquivos = [
    *RAIZ.glob("*.py"),
    *(f for pasta in PACOTES_DE_CODIGO for f in (RAIZ / pasta).rglob("*.py") if "__pycache__" not in f.parts),
    RAIZ / "requirements.txt",
    RAIZ / "README.md",
    *(RAIZ / "deploy").glob("*.ps1"),
    *(RAIZ / "deploy").glob("*.md"),
    *(RAIZ / "deploy").glob("Caddyfile*"),
    *(RAIZ / "dados").glob("secoes_*.parquet"),
    *(RAIZ / "dados").glob("logs_*.parquet"),
    *(RAIZ / "dados").glob("votos_*.parquet"),
    *(RAIZ / "dados").glob("candidatos_*.json"),
    *(RAIZ / "dados").glob("integ_*.parquet"),
    *(RAIZ / "resultados").glob("*.parquet"),
    *(RAIZ / "resultados").glob("*.json"),
]
arquivos = [a for a in arquivos if a.exists() and not a.name.startswith(("teste_", "logs_brutos"))]
if not any(a.name.startswith("secoes_") for a in arquivos):
    raise SystemExit("Nenhum dados/secoes_*.parquet encontrado. Rode antes: python coleta/baixar_dados.py")

with zipfile.ZipFile(SAIDA, "w", zipfile.ZIP_DEFLATED) as z:
    for a in sorted(arquivos):
        z.write(a, Path("esteleicao") / a.relative_to(RAIZ))

n_logs = sum(a.name.startswith("logs_") for a in arquivos)
print(f"{SAIDA.name}: {len(arquivos)} arquivos ({n_logs} UFs com logs), {SAIDA.stat().st_size / 1e6:,.0f} MB")
print("Copie para o servidor, extraia e siga deploy/LEIAME_WINDOWS.md")
