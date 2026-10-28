"""Integridade das urnas: efeito do software/mídia dentro do município, testes de dígitos, impressão digital
participação × voto, persistência do risco entre turnos. Tudo aqui é descritivo: comparação com seções do mesmo
município, com erro-padrão agrupado por município."""
from __future__ import annotations

import numpy as np
import pandas as pd


def efeito_dentro_municipio(df: pd.DataFrame, grupo: str, y: str, peso: str = "comparecimento",
                            min_secoes: int = 300, chave=("uf", "cd_municipio")) -> pd.DataFrame:
    """
    Quanto `y` difere, em média, entre as seções de cada nível de `grupo` e as OUTRAS seções do mesmo município
    (média ponderada por `peso`). Só entram municípios que têm mais de um nível. O erro-padrão trata cada município
    como um bloco (os erros de seções vizinhas se parecem), então os intervalos não são otimistas.
    Devolve: nivel, secoes, municipios, efeito, ep, z.
    """
    d = df[[*chave, grupo, y, peso]].dropna().copy()
    d[grupo] = d[grupo].astype(str)
    d = d[d[peso] > 0]
    k = list(chave)
    d = d[d.groupby(k, observed=True)[grupo].transform("nunique") > 1]
    d["wy"] = d[y] * d[peso]
    tot = d.groupby(k, observed=True)[["wy", peso]].transform("sum")
    d["dev"] = d[y] - tot["wy"] / tot[peso]
    d["wdev"] = d["dev"] * d[peso]
    linhas = []
    for nivel, g in d.groupby(grupo, observed=True):
        if len(g) < min_secoes:
            continue
        W = g[peso].sum()
        est = g["wdev"].sum() / W
        bloco = g.groupby(k, observed=True).agg(S=("wdev", "sum"), Wm=(peso, "sum"))
        ep = np.sqrt(((bloco["S"] - est * bloco["Wm"]) ** 2).sum()) / W
        linhas.append({"nivel": nivel, "secoes": len(g), "municipios": len(bloco), "efeito": est, "ep": ep,
                       "z": est / ep if ep > 0 else np.nan})
    return pd.DataFrame(linhas)


def ultimo_digito(v: pd.Series, minimo: int = 30) -> dict:
    """
    Último dígito dos totais por seção: sem manipulação, os 10 dígitos aparecem com a mesma frequência.
    Em totais pequenos a distribuição é inclinada (há mais seções com 52 do que com 59 votos) e isso, sozinho, já
    faz os dígitos baixos aparecerem mais. Por isso o esperado de cada valor é a média dos 20 valores vizinhos
    (a inclinação some, sobra só o efeito do dígito). Devolve contagens observada/esperada, n, qui² (9 g.l.) e p.
    """
    x = v[v >= minimo].astype(int).to_numpy()
    if len(x) < 200:
        return {"n": int(len(x)), "contagem": [0] * 10, "esperado": [0.0] * 10, "qui2": None, "p": None}
    c = np.bincount(x).astype(float)
    janela = np.convolve(c, np.ones(20) / 20, mode="same")     # centrada em n (n-10..n+9)
    n = np.arange(len(c))
    ok = (n >= x.min() + 10) & (n <= x.max() - 10)
    obs = np.array([c[ok & (n % 10 == d)].sum() for d in range(10)])
    esp = np.array([janela[ok & (n % 10 == d)].sum() for d in range(10)])
    qui = float(((obs - esp) ** 2 / esp).sum())
    return {"n": int(obs.sum()), "contagem": obs.astype(int).tolist(), "esperado": np.round(esp, 1).tolist(),
            "qui2": qui, "p": float(_p_qui2_9(qui))}


def _p_qui2_9(x: float) -> float:
    """Cauda do qui-quadrado com 9 g.l. (série; evita depender do scipy)."""
    # 9 g.l. é ímpar: P(X>x) = 2*(1-Phi(sqrt x)) + 2*phi(sqrt x)*sum_{k=0}^{3} (sqrt x)^(2k+1)/(1*3*..*(2k+1))
    from math import erfc, exp, pi, sqrt
    r = sqrt(x)
    soma, termo = 0.0, r
    for k in range(4):
        soma += termo
        termo *= r * r / (2 * k + 3)
    return erfc(r / sqrt(2)) + 2 * exp(-x / 2) / sqrt(2 * pi) * soma


def correlacao_participacao_voto(df: pd.DataFrame, part: str, voto: str, chave=("uf", "cd_municipio"),
                                 peso: str | None = None) -> float:
    """Correlação, DENTRO do município, entre participação e % de um candidato. Impressão digital clássica de
    inflar participação com votos de um lado só: correlação muito positiva e concentrada em poucas seções."""
    k = list(chave)
    d = df[[*k, part, voto]].dropna()
    d = d[d.groupby(k, observed=True)[part].transform("size") >= 5]
    a = d[part] - d.groupby(k, observed=True)[part].transform("mean")
    b = d[voto] - d.groupby(k, observed=True)[voto].transform("mean")
    den = np.sqrt((a * a).sum() * (b * b).sum())
    return float((a * b).sum() / den) if den else np.nan


def persistencia(f1: pd.Series, f2: pd.Series) -> dict:
    """Quanto as seções de risco no 1º turno voltam a ser de risco no 2º, contra as demais (razão = lift)."""
    f1, f2 = f1.astype(bool), f2.astype(bool)
    a = float(f2[f1].mean()) if f1.any() else np.nan
    b = float(f2[~f1].mean()) if (~f1).any() else np.nan
    return {"secoes_t1": int(f1.sum()), "t2_dado_t1": a, "t2_dado_nao_t1": b,
            "razao": a / b if b and b > 0 else np.nan, "ambos": int((f1 & f2).sum())}
