"""
Baixa o arquivo oficial do TSE "Votação por seção eleitoral" (votos de cada candidato
em cada seção, vindos dos boletins de urna) e gera, por turno, um arquivo compacto
(Parquet) com uma linha por seção e uma coluna por candidato à Presidência.

Uso:
    python coleta/baixar_votos.py                      # 2026, os dois turnos
    python coleta/baixar_votos.py --turno 2            # só o 2º turno
    python coleta/baixar_votos.py --zip caminho/votacao_secao_2026_BR.zip   # se já baixou o zip

Resultado:
    dados/votos_2026_t1.parquet   colunas: uf, cd_municipio, zona, secao, v_<número>...
    dados/candidatos_2026_t1.json {"13": "LUIZ INÁCIO LULA DA SILVA", ..., "95": "VOTO BRANCO", "96": "VOTO NULO"}
    (idem _t2)

v_95 = votos em branco, v_96 = votos nulos; os demais são o número do candidato.

Fonte: https://dadosabertos.tse.jus.br/dataset/resultados-2026 (Votação por seção eleitoral;
a Presidência fica no arquivo "BR", os demais cargos nos arquivos por UF).
"""
from __future__ import annotations

import argparse
import io
import json
import sys
import zipfile
from pathlib import Path

import pandas as pd

from download_tse import baixar_completo

URL = "https://cdn.tse.jus.br/estatistica/sead/odsele/votacao_secao/votacao_secao_{ano}_BR.zip"
PASTA = Path(__file__).resolve().parent.parent / "dados"
COLUNAS = ["NR_TURNO", "SG_UF", "CD_MUNICIPIO", "NR_ZONA", "NR_SECAO", "CD_CARGO",
           "NR_VOTAVEL", "NM_VOTAVEL", "QT_VOTOS"]
CHAVE = ["uf", "cd_municipio", "zona", "secao"]


def ler_zip(caminho: Path, turnos: list[int], cargo: int):
    """Soma os votos por seção e candidato. Devolve ({turno: DataFrame longo}, {turno: {número: nome}})."""
    partes = {t: [] for t in turnos}
    nomes = {t: {} for t in turnos}
    with zipfile.ZipFile(caminho) as z:
        csvs = [n for n in z.namelist() if n.lower().endswith(".csv")]
        if not csvs:
            sys.exit("Nenhum CSV dentro do zip.")
        for nome in csvs:
            print(f"Lendo {nome}")
            with z.open(nome) as bruto:
                cab = pd.read_csv(io.TextIOWrapper(bruto, encoding="latin-1"), sep=";", nrows=0).columns
            faltando = [c for c in COLUNAS if c not in cab]
            if faltando:
                sys.exit(f"Colunas ausentes em {nome}: {faltando}")
            with z.open(nome) as bruto:
                for pedaco in pd.read_csv(io.TextIOWrapper(bruto, encoding="latin-1"), sep=";",
                                          usecols=COLUNAS, dtype=str, chunksize=500_000):
                    pedaco = pedaco[pedaco["CD_CARGO"] == str(cargo)]
                    for t in turnos:
                        p = pedaco[pedaco["NR_TURNO"] == str(t)]
                        if p.empty:
                            continue
                        nomes[t].update(dict(zip(p["NR_VOTAVEL"], p["NM_VOTAVEL"])))
                        partes[t].append(p[["SG_UF", "CD_MUNICIPIO", "NR_ZONA", "NR_SECAO",
                                            "NR_VOTAVEL", "QT_VOTOS"]])
    return partes, nomes


def montar(partes: list[pd.DataFrame]) -> pd.DataFrame:
    df = pd.concat(partes, ignore_index=True).rename(columns={
        "SG_UF": "uf", "CD_MUNICIPIO": "cd_municipio", "NR_ZONA": "zona", "NR_SECAO": "secao"})
    df["QT_VOTOS"] = pd.to_numeric(df["QT_VOTOS"], errors="coerce").fillna(0).astype("int32")
    for c in ["cd_municipio", "zona", "secao"]:
        df[c] = pd.to_numeric(df[c], errors="coerce").astype("Int32")
    # soma (e não "first"): se o TSE repetir a linha de um candidato na seção, não perdemos votos
    largo = df.pivot_table(index=CHAVE, columns="NR_VOTAVEL", values="QT_VOTOS",
                           aggfunc="sum", fill_value=0, observed=True)
    largo.columns = [f"v_{int(c)}" for c in largo.columns]
    return largo.astype("int32").reset_index()


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--ano", type=int, default=2026)
    p.add_argument("--turno", type=int, choices=[1, 2], help="Padrão: os dois turnos")
    p.add_argument("--cargo", type=int, default=1, help="1 = Presidente (padrão)")
    p.add_argument("--zip", type=Path, help="Usar um zip já baixado em vez de baixar")
    a = p.parse_args()
    turnos = [a.turno] if a.turno else [1, 2]
    PASTA.mkdir(exist_ok=True)

    caminho = a.zip or baixar_completo(URL.format(ano=a.ano), PASTA / f"votacao_secao_{a.ano}_BR.zip")
    partes, nomes = ler_zip(caminho, turnos, a.cargo)
    for t in turnos:
        if not partes[t]:
            print(f"Turno {t}: sem linhas para o cargo {a.cargo} (o TSE já publicou?)")
            continue
        df = montar(partes[t])
        saida = PASTA / f"votos_{a.ano}_t{t}.parquet"
        df.to_parquet(saida, index=False)
        (PASTA / f"candidatos_{a.ano}_t{t}.json").write_text(
            json.dumps(nomes[t], ensure_ascii=False, indent=1), encoding="utf-8")
        cols = [c for c in df.columns if c.startswith("v_")]
        tot = df[cols].sum().sort_values(ascending=False)
        print(f"\nTurno {t}: {len(df):,} seções | {int(tot.sum()):,} votos no total")
        for c, v in tot.head(6).items():
            print(f"  {nomes[t].get(c[2:], c):<40} {int(v):>12,}")
        print(f"  Salvo em {saida}")


if __name__ == "__main__":
    main()
