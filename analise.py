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


# ====================================================================== horário dos votos
HORAS = [f"h{h:02d}" for h in range(24)]
MIN_VOTOS_HORARIO = 30      # seções com menos votos no log ficam fora do z de horário
PISO_ESCALA_HORARIO = 0.15  # horas (9 min): evita z enorme em municípios muito homogêneos


def resumo_coluna(df: pd.DataFrame, col: str, por: list[str] | None = None) -> pd.DataFrame:
    """Média, desvio padrão, mediana e percentis de uma métrica qualquer, por grupo."""
    df = df[list(dict.fromkeys((por or []) + [col]))]

    def _agg(g):
        x = g[col].dropna()
        return pd.Series({"secoes": len(x), "media": x.mean(), "desvio_padrao": x.std(ddof=1),
                          "mediana": x.median(), "p05": x.quantile(0.05), "p95": x.quantile(0.95),
                          "maximo": x.max()})
    if not por:
        return _agg(df).to_frame().T
    return df.groupby(por, observed=True).apply(_agg, include_groups=False).reset_index()


def _z_robusto(x: pd.Series, grupos: list[pd.Series], piso: float) -> pd.Series:
    """(x - mediana do grupo) / (1,4826 × MAD do grupo), com piso na escala."""
    med = x.groupby(grupos, observed=True).transform("median")
    mad = (x - med).abs().groupby(grupos, observed=True).transform("median") * 1.4826
    return (x - med) / np.maximum(mad, piso), med, np.maximum(mad, piso)


def corrigir_fuso(logs: pd.DataFrame) -> pd.DataFrame:
    """
    Reaplica a regra de fuso atual (logs_urna.fuso_por_abertura) a logs já processados,
    sem precisar baixar de novo. As contagens por hora local (h/s/m00..23) permitem
    recalcular exatamente os votos após 17h; horários médios são deslocados em horas inteiras.
    """
    from logs_urna import ABERTURA, ENCERRAMENTO, fuso_por_abertura
    if logs is None or logs.empty or "h00" not in logs:
        return logs
    logs = logs.copy()
    ref_local = logs["abertura"].fillna(logs["primeiro_voto"]) + logs["fuso"]
    novo = pd.Series([fuso_por_abertura(r, u) for r, u in zip(ref_local, logs["uf"].astype(str))],
                     index=logs.index)
    # harmoniza pelo fuso mais comum do município (como no processamento)
    novo = novo.groupby([logs["uf"], logs["cd_municipio"]]).transform(lambda s: s.mode().iloc[0])
    delta = novo - logs["fuso"]
    m = delta != 0
    if not m.any():
        return logs
    for c in ["hora_media", "hora_mediana", "hora_p90", "primeiro_voto", "ultimo_voto", "abertura"]:
        if c in logs:
            logs.loc[m, c] = logs.loc[m, c] - delta[m]
    if "abertura_atrasada_min" in logs:
        logs.loc[m, "abertura_atrasada_min"] = ((logs.loc[m, "abertura"] - ABERTURA) * 60).clip(lower=0)
    H = logs.loc[m, [f"h{h:02d}" for h in range(24)]].to_numpy()
    S = logs.loc[m, [f"s{h:02d}" for h in range(24)]].to_numpy() if "s00" in logs else None
    M = logs.loc[m, [f"m{h:02d}" for h in range(24)]].to_numpy() if "m00" in logs else None
    hora_local = np.arange(24)[None, :]
    f = novo[m].to_numpy()[:, None]
    apos = hora_local >= ENCERRAMENTO + f
    n = logs.loc[m, "votos_log"].to_numpy()
    va = (H * apos).sum(1)
    logs.loc[m, "votos_apos_17"] = va
    logs.loc[m, "pct_apos_17"] = va / np.maximum(n, 1)
    logs.loc[m, "pct_ultima_hora"] = (H * (hora_local == ENCERRAMENTO - 1 + f)).sum(1) / np.maximum(n, 1)
    logs.loc[m, "pct_manha"] = (H * (hora_local < 12 + f)).sum(1) / np.maximum(n, 1)
    if S is not None:
        logs.loc[m, "pct_sem_bio_apos_17"] = np.where(va > 0, (S * apos).sum(1) / np.maximum(va, 1), np.nan)
    if M is not None and "votos_manual_apos_17" in logs:
        logs.loc[m, "votos_manual_apos_17"] = (M * apos).sum(1)
    for c in ["ociosa_antes_17_min", "intervalo_med_apos_17_s"]:  # não dá para recalcular sem o log bruto
        if c in logs:
            logs.loc[m, c] = np.nan
    logs.loc[m, "fuso"] = novo[m]
    return logs


def juntar_horario(secoes: pd.DataFrame, logs: pd.DataFrame | None) -> pd.DataFrame:
    """
    Junta as métricas dos logs às seções e calcula:
      z_horario        hora média dos votos vs. demais seções do município (robusto).
                       Positivo = votação mais concentrada no fim do dia.
      dif_local_min    minutos de diferença da hora média para a mediana das OUTRAS
                       seções do mesmo local de votação (mesma escola = mesmas filas,
                       mesmo público). Fila legítima costuma atingir a escola inteira.
      score_cruzado    min(−z_ajustado, z_horario): só é alto se a seção tiver,
                       AO MESMO TEMPO, abstenção baixa e votação tardia.
      sinais           lista de padrões objetivos encontrados no log.
    """
    if logs is None or logs.empty:
        return secoes.assign(tem_log=False)
    chave = ["uf", "cd_municipio", "zona", "secao"]
    logs = corrigir_fuso(logs)
    for c in ["cd_municipio", "zona", "secao"]:
        logs[c] = logs[c].astype("Int32")
    logs["uf"] = logs["uf"].astype(str)
    sec = secoes.copy()
    sec["_uf"] = sec["uf"].astype(str)
    df = sec.merge(logs.rename(columns={"uf": "_uf"}), on=["_uf", "cd_municipio", "zona", "secao"],
                   how="left").drop(columns="_uf")
    df["tem_log"] = df["votos_log"].notna()

    ok = df["tem_log"] & (df["votos_log"] >= MIN_VOTOS_HORARIO)
    hm = df["hora_media"].where(ok)
    z_mun, _, _ = _z_robusto(hm, [df["uf"], df["cd_municipio"]], PISO_ESCALA_HORARIO)
    z_uf, _, _ = _z_robusto(hm, [df["uf"]], PISO_ESCALA_HORARIO)
    n_mun = hm.groupby([df["uf"], df["cd_municipio"]], observed=True).transform("count")
    df["z_horario"] = np.where(n_mun >= MIN_SECOES_MUNICIPIO, z_mun, z_uf)

    if "local" in df:
        g = [df["uf"], df["cd_municipio"], df["zona"], df["local"]]
        soma = hm.groupby(g, observed=True).transform("sum")
        cont = hm.groupby(g, observed=True).transform("count")
        media_outras = (soma - hm.fillna(0)) / (cont - hm.notna()).replace(0, np.nan)
        df["dif_local_min"] = (hm - media_outras) * 60
        df["secoes_no_local"] = cont

    df["score_cruzado"] = np.minimum(-df["z_ajustado"], df["z_horario"])
    # % dos votos após 17h comparado com o município (mesmo método das demais proporções)
    df["z_apos_17"], df["apos_17_esperado"] = z_proporcao(df, df["votos_apos_17"], df["votos_log"])

    # ---- habilitação sem digital
    if "votos_digital" in df:
        sem_dig = df["votos_log"] - df["votos_digital"]
        cadastrados = df["votos_log"] - df["votos_sem_cadastro"]
        df["pct_sem_digital"] = sem_dig / df["votos_log"]
        df["z_sem_digital"], df["sem_digital_esperado"] = z_proporcao(df, sem_dig, df["votos_log"])
        df["z_manual"], df["manual_esperado"] = z_proporcao(df, df["votos_manual"], cadastrados)
        if "local" in df:
            g = [df["uf"], df["cd_municipio"], df["zona"], df["local"]]
            s_n = sem_dig.groupby(g, observed=True).transform("sum")
            s_d = df["votos_log"].groupby(g, observed=True).transform("sum")
            outras = (s_n - sem_dig) / (s_d - df["votos_log"]).replace(0, np.nan)
            df["dif_local_sem_digital_pp"] = (df["pct_sem_digital"] - outras) * 100
    df["dif_log_comparecimento"] = df["votos_log"] - df["comparecimento"]

    s = pd.Series("", index=df.index)
    tarde = df["votos_apos_17"].fillna(0) >= 5

    def add(mask, texto):
        nonlocal s
        s = s.where(~mask.fillna(False), s + np.where(s == "", "", " · ") + texto)
    add(df["pct_apos_17"] >= 0.10, "≥10% dos votos após 17h")
    add(tarde & (df["ociosa_antes_17_min"] >= 20), "urna ociosa ≥20 min antes das 17h, mas votos depois")
    add(tarde & (df["pct_sem_bio_apos_17"] >= 0.5), "maioria sem biometria após 17h")
    add(tarde & (df["intervalo_med_apos_17_s"] <= 45), "votos após 17h em ritmo muito rápido")
    if "dif_local_min" in df:
        add(df["dif_local_min"] >= 60, "1h+ mais tarde que as outras seções da escola")
    if "z_sem_digital" in df:
        add(df["z_sem_digital"] >= 3, "sem digital muito acima do município")
        add(df["z_manual"] >= 3, "liberação manual (tinha digital) muito acima do município")
        add(df["maior_seq_manual"] >= 8, "8+ liberações manuais seguidas")
        if "dif_local_sem_digital_pp" in df:
            add(df["dif_local_sem_digital_pp"] >= 25, "sem digital 25+ p.p. acima das outras seções da escola")
    add(df["dif_log_comparecimento"].abs() >= 1, "votos no log ≠ comparecimento oficial")
    add(df["n_urnas"] > 1, "urna substituída")
    add(df["abertura_atrasada_min"] >= 30, "abertura atrasada ≥30 min")
    df["sinais"] = s.where(df["tem_log"], "")
    df["n_sinais"] = df["sinais"].str.count("·").add(1).where(df["sinais"] != "", 0)
    return df


def z_proporcao(df: pd.DataFrame, num: pd.Series, den: pd.Series, min_den: int = 30) -> tuple[pd.Series, pd.Series]:
    """
    Mesmo método do z ajustado da abstenção, para qualquer proporção num/den por seção:
    compara com a proporção do próprio município (sem contar a seção; UF se o município
    tiver menos de 5 seções), somando ao acaso binomial a variação natural entre seções
    (tau², estimada por UF de forma robusta). Devolve (z, proporção esperada).
    """
    ok = den >= min_den
    num, den = num.where(ok), den.where(ok)
    taxa = num / den
    g_mun = [df["uf"], df["cd_municipio"]]
    n_mun = taxa.groupby(g_mun, observed=True).transform("count")
    s_mun = num.groupby(g_mun, observed=True).transform("sum")
    d_mun = den.groupby(g_mun, observed=True).transform("sum")
    s_uf = num.groupby(df["uf"], observed=True).transform("sum")
    d_uf = den.groupby(df["uf"], observed=True).transform("sum")
    p_mun = (s_mun - num) / (d_mun - den).replace(0, np.nan)
    p_uf = (s_uf - num) / (d_uf - den).replace(0, np.nan)
    esperada = pd.Series(np.where(n_mun >= MIN_SECOES_MUNICIPIO, p_mun, p_uf), index=df.index)
    esperada = esperada.fillna(p_uf)
    p = esperada.clip(1e-3, 1 - 1e-3)
    var_acaso = p * (1 - p) / den
    resid = taxa - p

    def _tau2_uf(idx):
        r = resid.loc[idx].dropna()
        if len(r) < 20:
            return 0.0
        v = (1.4826 * (r - r.median()).abs().median()) ** 2
        return max(v - float(var_acaso.loc[r.index].median()), 0.0)
    tau2 = resid.groupby(df["uf"], observed=True).transform(lambda s: _tau2_uf(s.index))
    z = resid / np.sqrt(var_acaso + tau2)
    return z, esperada


def votos_por_hora(df: pd.DataFrame, prefixo: str = "h") -> pd.Series:
    """Votos por hora em horário equivalente (Brasília), somando as seções de df.
    prefixo: "h" = todos os votos, "s" = sem digital, "m" = liberação manual."""
    tot = np.zeros(30)
    cols = [f"{prefixo}{h:02d}" for h in range(24)]
    if cols[0] not in df:
        return pd.Series(tot[3:27], index=range(24))
    d = df.loc[df["tem_log"].astype(bool), ["fuso"] + cols]
    if d.empty:
        return pd.Series(tot[3:27], index=range(24))
    for fuso, g in d.groupby("fuso"):
        idx = np.arange(24) - int(fuso) + 3   # hora local h -> hora equivalente h - fuso
        tot[idx] += g[cols].sum().to_numpy(dtype=float)
    return pd.Series(tot[3:27], index=range(24))


def perfil_horario(df: pd.DataFrame) -> pd.Series:
    """Distribuição % dos votos por hora (horário equivalente), somando as seções de df."""
    v = votos_por_hora(df, "h")
    return v / max(v.sum(), 1)


# ====================================================================== comparação entre turnos
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
