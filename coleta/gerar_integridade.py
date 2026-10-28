"""
Gera os resultados ESTÁTICOS da área "Integridade das urnas" a partir do que `coleta/baixar_turno2.py` leu
(boletim de urna, RDV e log de cada seção do 2º turno) e dos dados já existentes em dados/.

    python coleta/gerar_integridade.py

Resultado (vai para o git):
    resultados/integridade_2026.parquet   uma linha por seção do 2º turno (software, verificações, risco nos dois turnos)
    resultados/integridade_2026.json      resumos: conciliação por UF, efeito do software, dígitos, impressão digital...
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
from analise import CHAVE_SECAO, juntar_horario, marcar_criterios, pontuar_secoes  # noqa: E402
from analise.integridade import (correlacao_participacao_voto, efeito_dentro_municipio, persistencia,  # noqa: E402
                                 ultimo_digito)

PASTA, SAIDA = RAIZ / "dados", RAIZ / "resultados"
ANO = 2026
K = CHAVE_SECAO


def _minutos(s: pd.Series, dia_ref: str) -> pd.Series:
    t = pd.to_datetime(s, errors="coerce")
    return (t - pd.Timestamp(dia_ref)).dt.total_seconds() / 60


def carregar_integ() -> pd.DataFrame:
    arqs = sorted(PASTA.glob(f"integ_{ANO}_t2_??.parquet"))
    if not arqs:
        raise SystemExit("Sem dados do 2º turno. Rode:  python coleta/baixar_turno2.py")
    print(f"{len(arqs)} UFs lidas do 2º turno: {', '.join(a.stem[-2:] for a in arqs)}")
    d = pd.concat([pd.read_parquet(a) for a in arqs], ignore_index=True)
    d["uf"] = d["uf"].astype(str)
    return d


def montar_base(integ: pd.DataFrame) -> pd.DataFrame:
    """Junta o que veio das urnas com o resultado oficial, o 1º turno e o risco dos dois turnos."""
    s1, s2 = (pd.read_parquet(PASTA / f"secoes_{ANO}_t{t}.parquet") for t in (1, 2))
    v2 = pd.read_parquet(PASTA / f"votos_{ANO}_t2.parquet")
    for x in (s1, s2, v2):
        x["uf"] = x["uf"].astype(str)
    s1, s2 = s1[s1.uf != "ZZ"], s2[s2.uf != "ZZ"]

    ufs = sorted(integ["uf"].unique())
    arqs_log = [PASTA / f"logs_{ANO}_t2_{u}.parquet" for u in ufs]
    b2 = juntar_horario(pontuar_secoes(s2[s2.uf.isin(ufs)]), pd.concat([pd.read_parquet(a) for a in arqs_log], ignore_index=True))
    f2 = pd.DataFrame(dict(zip(("f2_abst", "f2_17", "f2_man"), marcar_criterios(b2))), index=b2.index)
    b2 = pd.concat([b2, f2], axis=1)

    r1 = pd.read_parquet(RAIZ / "resultados" / f"risco_{ANO}.parquet")
    r1["uf"] = r1["uf"].astype(str)
    f1 = pd.DataFrame(dict(zip(("f1_abst", "f1_17", "f1_man"), marcar_criterios(r1))), index=r1.index)
    r1 = pd.concat([r1, f1], axis=1)

    base = integ.merge(s2[K + ["municipio", "aptos", "comparecimento", "brancos", "nulos", "taxa_abstencao"]], on=K, how="left")
    base = base.merge(s1[K + ["aptos", "comparecimento", "brancos", "nulos", "taxa_abstencao"]]
                      .rename(columns=lambda c: c if c in K else c + "_t1"), on=K, how="left")
    base = base.merge(v2[K + ["v_13", "v_22", "v_95", "v_96"]], on=K, how="left")
    cols_log = K + ["votos_log", "pct_apos_17", "votos_apos_17", "pct_manual_cadastrados", "votos_manual",
                    "pct_sem_digital", "z_ajustado", "z_manual", "dif_local_min", "f2_abst", "f2_17", "f2_man"]
    base = base.merge(b2[[c for c in cols_log if c in b2]].rename(columns={"votos_log": "log_votos", "votos_manual": "manual"}),
                      on=K, how="left")
    base = base.merge(r1[K + ["z_desvio_13", "votos1_13", "votos2_13", "validos1", "validos2", "f1_abst", "f1_17", "f1_man",
                              "z_ajustado", "pct_apos_17"]].rename(columns={"z_ajustado": "z_abst_t1", "pct_apos_17": "pct_apos_17_t1"}),
                      on=K, how="left")
    for c in ("f1_abst", "f1_17", "f1_man", "f2_abst", "f2_17", "f2_man"):
        base[c] = base[c].fillna(False).astype(bool)

    comp = base["comparecimento"].replace(0, np.nan)
    base["bn_pct"] = (base["bu_p_branco"] + base["bu_p_nulo"]) / base["bu_comparecimento"].replace(0, np.nan)
    base["bn_pct_t1"] = (base["brancos_t1"] + base["nulos_t1"]) / base["comparecimento_t1"].replace(0, np.nan)
    base["lula_pct"] = base["bu_p_13"] / (base["bu_p_13"] + base["bu_p_22"]).replace(0, np.nan)
    base["lula_pct_t1"] = base["votos1_13"] / base["validos1"].replace(0, np.nan)
    base["part"] = base["comparecimento"] / base["aptos"].replace(0, np.nan)
    base["d_bn_pp"] = (base["bn_pct"] - base["bn_pct_t1"]) * 100
    base["d_abst_pp"] = (base["taxa_abstencao"] - base["taxa_abstencao_t1"]) * 100
    base["d_lula_pp"] = (base["lula_pct"] - base["lula_pct_t1"]) * 100
    base["abertura_min"] = _minutos(base["bu_abertura"], "2026-10-25")
    base["encerramento_min"] = _minutos(base["bu_encerramento"], "2026-10-25")
    base["carga_data"] = base["bu_carga_dt"].astype(str).str[:10]
    base["chk_bu_oficial"] = ((base["bu_p_13"] == base["v_13"]) & (base["bu_p_22"] == base["v_22"])
                              & ((base["bu_p_branco"] == base["v_95"]) | base["v_95"].isna())).where(base["v_13"].notna())
    base["comparecimento"] = base["comparecimento"].fillna(base["bu_comparecimento"])
    return base


def resumo_conciliacao(b: pd.DataFrame) -> list[dict]:
    out = []
    for uf, g in b.groupby("uf"):
        n = len(g)
        out.append({"uf": uf, "secoes": n,
                    "bu_diferente_rdv": int((~g["chk_bu_rdv"].astype(bool)).sum()),
                    "bu_diferente_comparecimento": int((~g["chk_bu_comp"].astype(bool)).sum()),
                    "log_diferente_bu": int((~g["chk_log_bu"].astype(bool)).sum()),
                    "habilitados_diferente_votos": int((~g["chk_conf_pres"].astype(bool)).sum()),
                    "bu_diferente_oficial": int((g["chk_bu_oficial"] == False).sum()),  # noqa: E712
                    "sem_oficial": int(g["chk_bu_oficial"].isna().sum())})
    return out


GRUPOS_SOFT = {"log_modelo": "Modelo da urna", "log_versao": "Versão do software", "log_uefi": "Firmware (UEFI)",
               "carga_data": "Data da carga", "bu_midia_pc": "Computador gerador da mídia",
               "assin_falha": "Falha de assinatura no log", "faixa_erros": "Erros no log da urna"}
RESULTADOS = {"z_desvio_13": "Lula acima/abaixo do esperado (z)", "d_lula_pp": "Variação do Lula 1º→2º (p.p.)",
              "bn_pct": "Brancos+nulos 2º turno (fração)", "d_bn_pp": "Variação de brancos+nulos (p.p.)",
              "d_abst_pp": "Variação da abstenção (p.p.)"}


def efeitos_software(b: pd.DataFrame) -> list[dict]:
    d = b.copy()
    d["assin_falha"] = np.where(d["log_assin_falha"] > 0, "com falha", "sem falha")
    d["faixa_erros"] = pd.cut(d["log_n_erro"], [-1, 0, 2, 10_000], labels=["0 erros", "1–2 erros", "3+ erros"]).astype(str)
    d["bu_midia_pc"] = d["bu_midia_pc"].astype(str).str[:6]   # prefixo identifica o grupo/gerador, sem expor série
    d["cd_municipio"] = d["cd_municipio"].astype(int)
    linhas = []
    for g, rot in GRUPOS_SOFT.items():
        if g not in d:
            continue
        for y, roty in RESULTADOS.items():
            e = efeito_dentro_municipio(d, g, y, min_secoes=100)
            for r in e.to_dict("records"):
                linhas.append({"grupo": g, "grupo_rotulo": rot, "resultado": y, "resultado_rotulo": roty, **r})
    return linhas


def forense(b: pd.DataFrame) -> dict:
    out = {"digitos": [], "impressao": []}
    v1 = pd.read_parquet(PASTA / f"votos_{ANO}_t1.parquet")
    v1["uf"] = v1["uf"].astype(str)
    ufs = sorted(b["uf"].unique())
    for uf in ["BR", *ufs]:
        g = b if uf == "BR" else b[b["uf"] == uf]
        h = v1 if uf == "BR" else v1[v1["uf"] == uf]
        h = h[h.uf.isin(ufs)]
        out["digitos"].append({"uf": uf, "lula_t2": ultimo_digito(g["bu_p_13"]), "flavio_t2": ultimo_digito(g["bu_p_22"]),
                               "lula_t1": ultimo_digito(h["v_13"]) if "v_13" in h else None})
        gg = g.assign(p=g["part"], l=g["lula_pct"])
        out["impressao"].append({"uf": uf, "corr_t2": correlacao_participacao_voto(gg, "p", "l"),
                                 "corr_t1": correlacao_participacao_voto(
                                     g.assign(p=g["comparecimento_t1"] / g["aptos_t1"].replace(0, np.nan), l=g["lula_pct_t1"]), "p", "l"),
                                 "part_95_lula_90": int(((g["part"] >= 0.95) & (g["lula_pct"] >= 0.90)).sum()),
                                 "part_95_flavio_90": int(((g["part"] >= 0.95) & (g["lula_pct"] <= 0.10)).sum())})
    return out


def persist(b: pd.DataFrame) -> list[dict]:
    com = b[b["f1_abst"].notna()]
    nomes = {"abst": "Abstenção baixa", "17": "Voto após 17h", "man": "Liberação manual"}
    linhas = [{"criterio": n, **persistencia(com[f"f1_{k}"], com[f"f2_{k}"])} for k, n in nomes.items()]
    return linhas


def main():
    SAIDA.mkdir(exist_ok=True)
    integ = carregar_integ()
    base = montar_base(integ)
    print(f"{len(base):,} seções com leitura do 2º turno")

    resumo = {
        "ano": ANO, "secoes": len(base), "ufs": sorted(base["uf"].unique().tolist()),
        "conciliacao": resumo_conciliacao(base),
        "software": efeitos_software(base),
        "forense": forense(base),
        "persistencia": persist(base),
        "composicao": {g: base[g].astype(str).value_counts().head(12).to_dict()
                       for g in ("log_modelo", "log_versao", "log_uefi", "carga_data")},
    }
    (SAIDA / f"integridade_{ANO}.json").write_text(json.dumps(resumo, ensure_ascii=False, indent=1, default=float), encoding="utf-8")

    manter = (K + ["municipio", "log_modelo", "log_versao", "log_uefi", "carga_data", "bu_midia_pc", "log_assin_falha", "log_n_erro",
                   "log_n_alerta", "d2_dur_med", "d2_dur_lt10", "d2_teclas_indevidas", "d2_manual", "d2_suspensos", "d2_desligamentos",
                   "chk_bu_rdv", "chk_bu_comp", "chk_log_bu", "chk_conf_pres", "chk_bu_oficial", "bu_aptos", "bu_comparecimento",
                   "bu_p_13", "bu_p_22", "bu_p_branco", "bu_p_nulo", "log_votos", "abertura_min", "encerramento_min",
                   "bn_pct", "lula_pct", "part", "d_bn_pp", "d_abst_pp", "d_lula_pp", "z_desvio_13",
                   "f1_abst", "f1_17", "f1_man", "f2_abst", "f2_17", "f2_man", "pct_apos_17", "pct_apos_17_t1"])
    out = base[[c for c in manter if c in base]].copy()
    for c in out.select_dtypes("float64").columns:
        out[c] = out[c].astype("float32")
    for c in ("uf", "municipio", "log_modelo", "log_versao", "log_uefi", "carga_data", "bu_midia_pc"):
        out[c] = out[c].astype(str).astype("category")
    destino = SAIDA / f"integridade_{ANO}.parquet"
    out.to_parquet(destino, index=False, compression="zstd", compression_level=9)
    print(f"→ {destino} ({destino.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
