"""
Gera o arquivo ESTÁTICO da aba "Risco × melhora": para cada seção com log do 1º turno, as métricas dos três
critérios de risco (abstenção baixa, voto após 17h, liberação manual) e o desempenho dos candidatos no 2º turno
em relação ao município. O painel lê este arquivo; em produção não é preciso baixar logs nem ter os `.parquet`
de `dados/` para esta aba.

Uso (precisa dos dados em dados/: secoes_*_t1/t2, votos_*_t1/t2, logs_*_t1_<UF>):
    python gerar_resultado_risco.py
    python gerar_resultado_risco.py --ano 2026

Resultado: resultados/risco_<ano>.parquet  (este arquivo VAI para o git)
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from analise import CHAVE_SECAO, candidatos_comuns, comparar_turnos, juntar_horario, pontuar_secoes

RAIZ = Path(__file__).parent
PASTA, SAIDA = RAIZ / "dados", RAIZ / "resultados"
# métricas do log do 1º turno usadas pelos três critérios (mantê-las alinhadas a analise.marcar_criterios)
COLS_LOG = ["aptos", "taxa_abstencao", "z_ajustado", "z_binomial", "z_simples", "pct_apos_17", "votos_apos_17",
            "dif_local_min", "z_manual", "votos_manual", "pct_manual_cadastrados", "pct_sem_digital"]


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--ano", type=int, default=2026)
    a = p.parse_args()
    ano = a.ano

    s1, s2 = (pd.read_parquet(PASTA / f"secoes_{ano}_t{t}.parquet") for t in (1, 2))
    v1, v2 = (pd.read_parquet(PASTA / f"votos_{ano}_t{t}.parquet") for t in (1, 2))
    arqs = sorted(PASTA.glob(f"logs_{ano}_t1_*.parquet"))
    if not arqs:
        raise SystemExit("Sem logs do 1º turno em dados/. Rode:  python baixar_logs.py --turno 1")
    s1, s2 = s1[s1["uf"].astype(str) != "ZZ"], s2[s2["uf"].astype(str) != "ZZ"]
    print(f"{len(arqs)} UFs com log do 1º turno")

    base = juntar_horario(pontuar_secoes(s1), pd.concat([pd.read_parquet(f) for f in arqs], ignore_index=True))
    base = base[base["tem_log"].astype(bool)]
    out = base[CHAVE_SECAO + [c for c in COLS_LOG if c in base]].copy()
    out["uf"] = out["uf"].astype(str)

    cands = candidatos_comuns(v1, v2)
    print("Candidatos nos dois turnos:", cands)
    for i, c in enumerate(cands):
        d = comparar_turnos(s1, s2, v1, v2, c)
        d["uf"] = d["uf"].astype(str)
        cols = CHAVE_SECAO + [f"{k}_{c}" for k in ("votos1", "votos2", "esperado_pp", "z_desvio")]
        d = d.rename(columns={"votos1": f"votos1_{c}", "votos2": f"votos2_{c}", "esperado_pp": f"esperado_pp_{c}",
                              "z_desvio": f"z_desvio_{c}"})
        extra = ["municipio", "nome_local", "validos1", "validos2"] if i == 0 else []
        out = out.merge(d[cols + extra], on=CHAVE_SECAO, how="inner")
    out = out[(out["validos1"] >= 30) & (out["validos2"] >= 30)].reset_index(drop=True)

    for c in out.select_dtypes("float64").columns:
        out[c] = out[c].astype("float32")
    for c in ["municipio", "nome_local"]:
        out[c] = out[c].astype(str).astype("category")
    for c in ["uf"]:
        out[c] = out[c].astype("category")
    SAIDA.mkdir(exist_ok=True)
    destino = SAIDA / f"risco_{ano}.parquet"
    out.to_parquet(destino, index=False, compression="zstd")
    meta = {"ano": ano, "secoes": len(out), "ufs": sorted(out["uf"].astype(str).unique()), "candidatos": cands}
    (SAIDA / f"risco_{ano}.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{len(out):,} seções, {len(meta['ufs'])} UFs → {destino} ({destino.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
