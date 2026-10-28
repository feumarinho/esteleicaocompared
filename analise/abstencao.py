"""
Cálculos estatísticos de abstenção por seção.

Três medidas de "quão fora do normal" uma seção está, todas em relação ao
próprio município (ou à UF, quando o município tem poucas seções):

1. z_simples    = (taxa da seção - média das seções) / desvio padrão das seções
                  É o que se pede intuitivamente, mas penaliza seções pequenas:
                  uma seção com 40 eleitores varia muito mais por puro acaso.

2. z_binomial   = (abstenções observadas - esperadas) / sqrt(aptos * p * (1-p))
                  Leva em conta o tamanho da seção (cada eleitor como "moeda").

3. z_ajustado   = (taxa - esperada) / sqrt(p(1-p)/aptos + tau²)   <- RECOMENDADO
                  tau² é a variação "real" entre seções que existe mesmo sem
                  nada de errado (perfil de idade, renda, cadastro desatualizado,
                  zona rural...). Sem ele, quase tudo vira "anomalia". tau² é
                  estimado por UF de forma robusta (mediana/MAD, que não se deixa
                  levar pelos próprios outliers) — modelo de efeitos aleatórios
                  aditivo usado em funnel plots (Spiegelhalter, 2005).
                  Com isso, |z_ajustado| > 3 fica raro de verdade.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

MIN_SECOES_MUNICIPIO = 5  # abaixo disso, a referência é a UF


def resumo(df: pd.DataFrame, por: list[str] | None = None) -> pd.DataFrame:
    """Média, desvio padrão etc. da taxa de abstenção das seções, por grupo."""
    df = df[list(dict.fromkeys((por or []) + ["taxa_abstencao", "aptos", "abstencoes"]))]  # só o necessário

    def _agg(g):
        t = g["taxa_abstencao"]
        mediana = t.median()
        return pd.Series({
            "secoes": len(g),
            "aptos": int(g["aptos"].sum()),
            "abstencoes": int(g["abstencoes"].sum()),
            "taxa_agregada": g["abstencoes"].sum() / g["aptos"].sum(),
            "media": t.mean(),
            "desvio_padrao": t.std(ddof=1) if len(g) > 1 else np.nan,
            "mediana": mediana,
            "mad": 1.4826 * (t - mediana).abs().median(),
            "p05": t.quantile(0.05),
            "p95": t.quantile(0.95),
            "minimo": t.min(),
            "maximo": t.max(),
        })
    if not por:
        return _agg(df).to_frame().T
    return df.groupby(por, observed=True).apply(_agg, include_groups=False).reset_index()


def _tau2(g: pd.DataFrame) -> float:
    """Variância entre seções além do acaso binomial, estimada de forma robusta."""
    r = (g["taxa_abstencao"] - g["taxa_esperada"]).dropna()
    if len(r) < 20:
        return 0.0
    var_robusta = (1.4826 * (r - r.median()).abs().median()) ** 2
    var_acaso = float((g["taxa_esperada"] * (1 - g["taxa_esperada"]) / g["aptos"]).median())
    return max(var_robusta - var_acaso, 0.0)


def pontuar_secoes(df: pd.DataFrame) -> pd.DataFrame:
    """Adiciona z-scores e referência a cada seção."""
    df = df.copy()
    chave_mun = ["uf", "cd_municipio"]

    mun = df.groupby(chave_mun, observed=True).agg(
        mun_secoes=("aptos", "size"), mun_aptos=("aptos", "sum"),
        mun_abst=("abstencoes", "sum"), mun_media=("taxa_abstencao", "mean"),
        mun_dp=("taxa_abstencao", "std")).reset_index()
    uf = df.groupby("uf", observed=True).agg(
        uf_aptos=("aptos", "sum"), uf_abst=("abstencoes", "sum"),
        uf_media=("taxa_abstencao", "mean"), uf_dp=("taxa_abstencao", "std")).reset_index()
    df = df.merge(mun, on=chave_mun, how="left").merge(uf, on="uf", how="left")

    usa_mun = df["mun_secoes"] >= MIN_SECOES_MUNICIPIO
    df["referencia"] = np.where(usa_mun, "município", "UF")

    # "leave-one-out": a própria seção não entra na média com que é comparada
    p_mun = (df["mun_abst"] - df["abstencoes"]) / (df["mun_aptos"] - df["aptos"]).replace(0, np.nan)
    p_uf = (df["uf_abst"] - df["abstencoes"]) / (df["uf_aptos"] - df["aptos"])
    df["taxa_esperada"] = np.where(usa_mun, p_mun, p_uf)
    df["taxa_esperada"] = df["taxa_esperada"].fillna(df["uf_abst"] / df["uf_aptos"])

    media_ref = np.where(usa_mun, df["mun_media"], df["uf_media"])
    dp_ref = np.where(usa_mun, df["mun_dp"], df["uf_dp"])
    df["z_simples"] = (df["taxa_abstencao"] - media_ref) / np.where(dp_ref > 0, dp_ref, np.nan)

    p = df["taxa_esperada"].clip(1e-4, 1 - 1e-4)
    df["abst_esperadas"] = df["aptos"] * p
    df["z_binomial"] = (df["abstencoes"] - df["abst_esperadas"]) / np.sqrt(df["aptos"] * p * (1 - p))

    tau2 = df.groupby("uf", observed=True)[["taxa_abstencao", "taxa_esperada", "aptos"]] \
        .apply(_tau2).rename("tau2")
    df = df.merge(tau2, left_on="uf", right_index=True, how="left")
    df["z_ajustado"] = (df["taxa_abstencao"] - p) / np.sqrt(p * (1 - p) / df["aptos"] + df["tau2"])

    # percentil da seção dentro do município e do Brasil
    df["pct_municipio"] = df.groupby(chave_mun, observed=True)["taxa_abstencao"].rank(pct=True)
    df["pct_brasil"] = df["taxa_abstencao"].rank(pct=True)

    descartar = ["mun_aptos", "mun_abst", "uf_aptos", "uf_abst"]
    return df.drop(columns=descartar)


def limites_funil(p: float, tau2: float, n_max: int, k: float) -> pd.DataFrame:
    """Curvas de controle (funnel plot) para média p, variação extra tau² e k desvios."""
    n = np.unique(np.geomspace(10, max(n_max, 20), 200).astype(int))
    sd = np.sqrt(p * (1 - p) / n + tau2)
    return pd.DataFrame({"aptos": n, "inf": np.clip(p - k * sd, 0, 1), "sup": np.clip(p + k * sd, 0, 1)})
