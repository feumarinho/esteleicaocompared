"""Comparação do desempenho dos candidatos entre o 1º e o 2º turno, seção a seção."""
from __future__ import annotations

import numpy as np
import pandas as pd

from .abstencao import MIN_SECOES_MUNICIPIO


BRANCO, NULO = 95, 96          # "números" de voto em branco e nulo no arquivo do TSE
MIN_VALIDOS_COMPARACAO = 30    # seções com menos votos válidos em algum turno ficam sem z
CHAVE_SECAO = ["uf", "cd_municipio", "zona", "secao"]


def candidatos_comuns(v1: pd.DataFrame, v2: pd.DataFrame) -> list[int]:
    """Números dos candidatos que têm votos nos dois turnos (sem branco e nulo)."""
    def nums(v):
        return {int(c[2:]) for c in v.columns if c.startswith("v_") and v[c].sum() > 0}
    return sorted(nums(v1) & nums(v2) - {BRANCO, NULO})


def _logit(votos, validos):
    """log(votos/não-votos) com correção de 0,5 (aguenta seções com 0% ou 100%)."""
    return np.log((votos + 0.5) / (validos - votos + 0.5))


def _var_logit(votos, validos):
    return 1 / (votos + 0.5) + 1 / (validos - votos + 0.5)


def _ajuste_variancia(r: pd.Series, v: pd.Series, bins: int = 10) -> tuple[float, float]:
    """(tau², k) tal que Var(resíduo) ≈ tau² + k × v, estimado de forma robusta por faixas de v."""
    df = pd.DataFrame({"r": r, "v": v}).dropna()
    if len(df) < 200:
        return np.nan, np.nan
    df["faixa"] = pd.qcut(df["v"], min(bins, len(df) // 50), duplicates="drop")
    g = df.groupby("faixa", observed=True)
    x = g["v"].median().to_numpy()
    y = g["r"].apply(lambda s: (1.4826 * (s - s.median()).abs().median()) ** 2).to_numpy()
    k, tau2 = np.polyfit(x, y, 1)
    if tau2 < 0:   # sem variação extra: ajusta só a inclinação
        tau2, k = 0.0, float((x * y).sum() / (x * x).sum())
    if k < 0:      # tamanho da seção não explica nada: variância constante
        k, tau2 = 0.0, float(np.median(y))
    return float(tau2), float(k)


def _variancia_calibrada(resid: pd.Series, var_acaso: pd.Series, uf: pd.Series) -> pd.Series:
    """
    Variância esperada do resíduo de cada seção: tau² + k × (acaso dos dois turnos).
    O acaso teórico (var_acaso) trata os dois turnos como independentes, mas são os MESMOS
    eleitores votando duas vezes, então a variação real da diferença é menor (k < 1). Por isso
    tau² e k são calibrados com os próprios dados, por UF (nacional se a UF tiver poucas seções),
    de forma robusta (MAD), para não se deixar levar pelos próprios outliers.
    """
    tau_br, k_br = _ajuste_variancia(resid, var_acaso)
    par = {u: _ajuste_variancia(resid[m], var_acaso[m]) for u, m in
           ((u, uf == u) for u in uf.dropna().unique())}
    tau2 = uf.map({u: p[0] if not np.isnan(p[0]) else tau_br for u, p in par.items()}).astype(float)
    k = uf.map({u: p[1] if not np.isnan(p[1]) else k_br for u, p in par.items()}).astype(float)
    return tau2 + k * var_acaso.fillna(var_acaso.median())


def comparar_turnos(s1: pd.DataFrame, s2: pd.DataFrame, v1: pd.DataFrame, v2: pd.DataFrame,
                    cand: int) -> pd.DataFrame:
    """
    Compara o desempenho de um candidato em cada seção no 1º e no 2º turno.

    Absoluto:  votos1, votos2, delta_votos (= votos2 − votos1).
    Relativo:  pct1, pct2 = % dos votos VÁLIDOS da seção (sem branco/nulo);
               delta_pp = pct2 − pct1, em pontos percentuais.

    Desvio em relação ao município: o município inteiro (sem contar a própria seção; UF se
    tiver menos de 5 seções) teve uma variação média (a "onda" do município, medida em logit
    para não ultrapassar 0–100%). A seção esperada é a que sobe/desce o mesmo tanto que o município:
        esperado_pp = pct1 deslocado pela onda do município
        desvio_pp   = pct2 − esperado_pp        (>0: foi melhor que o município; <0: pior)
        votos_vs_esperado = votos2 − esperado × válidos2   (o mesmo desvio, em votos)
    z_desvio divide o desvio (em logit) pela variação típica entre turnos de seções do mesmo tamanho
    na UF (calibrada com os dados, de forma robusta; ver _variancia_calibrada). Escala ~1 = normal.
    """
    col = f"v_{cand}"
    ref = s1[CHAVE_SECAO + [c for c in ["municipio", "local", "nome_local", "endereco_local", "aptos"]
                            if c in s1]]
    ref = ref.merge(s2[CHAVE_SECAO + ["aptos", "comparecimento"]].rename(
        columns={"aptos": "aptos2", "comparecimento": "comparecimento2"}), on=CHAVE_SECAO, how="left")

    def _preparar(v, n):
        cols = [c for c in (col, f"v_{BRANCO}", f"v_{NULO}") if c in v]
        tot = v[[c for c in v.columns if c.startswith("v_")]].sum(axis=1)
        out = v[CHAVE_SECAO].copy()
        out[f"votos{n}"] = v[col].astype("int32")
        out[f"validos{n}"] = (tot - sum(v[f"v_{x}"] for x in (BRANCO, NULO) if f"v_{x}" in v)).astype("int32")
        out[f"comparecimento_log{n}"] = tot.astype("int32")
        return out
    d = ref.merge(_preparar(v1, 1), on=CHAVE_SECAO, how="inner") \
           .merge(_preparar(v2, 2), on=CHAVE_SECAO, how="inner")
    d = d[(d["validos1"] > 0) & (d["validos2"] > 0)].reset_index(drop=True)

    d["delta_votos"] = d["votos2"] - d["votos1"]
    d["pct1"] = d["votos1"] / d["validos1"]
    d["pct2"] = d["votos2"] / d["validos2"]
    d["delta_pp"] = d["pct2"] - d["pct1"]
    d["taxa_abst1"] = 1 - d["comparecimento_log1"] / d["aptos"]
    d["taxa_abst2"] = 1 - d["comparecimento_log2"] / d["aptos2"]
    d["var_abst_pp"] = d["taxa_abst2"] - d["taxa_abst1"]   # negativo = abstenção caiu

    # variação do município (ou da UF) SEM a própria seção, na escala logit (log da razão
    # voto/não-voto): uma seção que já tinha 97% não "estoura" 100% como aconteceria somando pontos.
    def soma(k, g):
        return d[k].groupby(g, observed=True).transform("sum")
    g_mun, g_uf = [d["uf"], d["cd_municipio"]], d["uf"]
    n_mun = d["votos1"].groupby(g_mun, observed=True).transform("size")
    onda = {}
    for nome, g in (("mun", g_mun), ("uf", g_uf)):
        a1, b1 = soma("votos1", g) - d["votos1"], soma("validos1", g) - d["validos1"]
        a2, b2 = soma("votos2", g) - d["votos2"], soma("validos2", g) - d["validos2"]
        onda[nome] = _logit(a2, b2) - _logit(a1, b1)
    usa_mun = n_mun >= MIN_SECOES_MUNICIPIO
    d["referencia"] = np.where(usa_mun, "município", "UF")
    onda_l = pd.Series(np.where(usa_mun, onda["mun"], onda["uf"]), index=d.index) \
        .fillna(onda["uf"]).fillna(0.0)

    l1, var1 = _logit(d["votos1"], d["validos1"]), _var_logit(d["votos1"], d["validos1"])
    l2, var2 = _logit(d["votos2"], d["validos2"]), _var_logit(d["votos2"], d["validos2"])
    esperado_l = l1 + onda_l
    d["onda_pp"] = (1 / (1 + np.exp(-(_logit(d["votos1"], d["validos1"]) + onda_l))) - d["pct1"])
    d["esperado_pp"] = 1 / (1 + np.exp(-esperado_l))
    d["desvio_pp"] = d["pct2"] - d["esperado_pp"]
    d["votos_vs_esperado"] = d["votos2"] - d["esperado_pp"] * d["validos2"]

    ok = (d["validos1"] >= MIN_VALIDOS_COMPARACAO) & (d["validos2"] >= MIN_VALIDOS_COMPARACAO)
    var_acaso = (var1 + var2).where(ok)
    resid = (l2 - esperado_l).where(ok)
    d["z_desvio"] = resid / np.sqrt(_variancia_calibrada(resid, var_acaso, d["uf"]))
    return d
