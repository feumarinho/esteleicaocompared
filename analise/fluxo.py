"""Fluxo de votos entre turnos (regressão ecológica, NNLS em numpy, totais fechados por IPF)."""
from __future__ import annotations

import numpy as np
import pandas as pd

from .abstencao import MIN_SECOES_MUNICIPIO  # noqa: F401
from .turnos import BRANCO, CHAVE_SECAO, NULO


def _nnls_gram(G: np.ndarray, h: np.ndarray) -> np.ndarray:
    """Mínimos quadrados com coeficientes >= 0 (Lawson–Hanson) a partir de G = X'X e h = X'y.
    Escrito em numpy para não exigir scipy; o problema é pequeno (poucas origens)."""
    n = len(h)
    x, passivo = np.zeros(n), np.zeros(n, bool)
    tol = 1e-10 * max(1.0, float(np.abs(h).max()))
    w = h - G @ x
    for _ in range(10 * n + 10):
        if passivo.all() or w[~passivo].max() <= tol:
            break
        passivo[np.where(~passivo)[0][np.argmax(w[~passivo])]] = True
        while True:
            s = np.zeros(n)
            idx = np.where(passivo)[0]
            s[idx] = np.linalg.solve(G[np.ix_(idx, idx)] + 1e-12 * np.eye(len(idx)), h[idx])
            if s[idx].min() > 0:
                x = s
                break
            neg = passivo & (s <= 0)
            alfa = np.min(x[neg] / (x[neg] - s[neg] + 1e-300))
            x = x + alfa * (s - x)
            passivo &= x > 1e-12
            x[~passivo] = 0.0
        w = h - G @ x
    return x


def _fechar_totais(F: np.ndarray, origem: np.ndarray, destino: np.ndarray, iteracoes: int = 300) -> np.ndarray:
    """Ajusta a matriz de fluxos (IPF) para que as linhas somem o total de cada origem
    e as colunas o total de cada destino."""
    F = np.maximum(F, 1e-9)
    for _ in range(iteracoes):
        F = F * (origem / F.sum(1))[:, None]
        F = F * (destino / F.sum(0))[None, :]
    return np.where(F < 500, 0.0, F)   # < 500 votos é resíduo numérico do ajuste, não fluxo


def preparar_fluxo(s1: pd.DataFrame, s2: pd.DataFrame, v1: pd.DataFrame, v2: pd.DataFrame,
                   finalistas: list[int], n_individuais: int = 3) -> dict:
    """
    Resume cada município em matrizes pequenas (X'X e X'y de cada destino), o que permite estimar
    o fluxo de qualquer conjunto de UFs e reamostrar municípios (bootstrap) quase de graça.

    Origens (1º turno):  finalistas, os maiores candidatos eliminados (um a um), os demais
                         candidatos juntos, branco+nulo, abstenção.
    Destinos (2º turno): finalistas, branco+nulo, abstenção.
    """
    v1 = v1.rename(columns={c: c + "_1" for c in v1 if c.startswith("v_")})
    v2 = v2.rename(columns={c: c + "_2" for c in v2 if c.startswith("v_")})
    d = s1[CHAVE_SECAO + ["aptos"]].merge(v1, on=CHAVE_SECAO).merge(
        s2[CHAVE_SECAO + ["aptos"]].rename(columns={"aptos": "aptos2"}), on=CHAVE_SECAO).merge(v2, on=CHAVE_SECAO)
    d = d[d["aptos"] > 0].reset_index(drop=True)
    c1 = [c for c in d if c.startswith("v_") and c.endswith("_1")]
    c2 = [c for c in d if c.startswith("v_") and c.endswith("_2")]
    tot1, tot2 = d[c1].sum(axis=1), d[c2].sum(axis=1)
    num = lambda c: int(c[2:-2])
    eliminados = sorted((c for c in c1 if num(c) not in (*finalistas, BRANCO, NULO)),
                        key=lambda c: -d[c].sum())
    indiv, demais = eliminados[:n_individuais], eliminados[n_individuais:]
    origens = {f"f{n}": d[f"v_{n}_1"] for n in finalistas}
    for c in indiv:
        origens[f"c{num(c)}"] = d[c]
    if demais:
        origens["demais"] = d[demais].sum(axis=1)
    origens["brancos_nulos"] = d.get(f"v_{BRANCO}_1", 0) + d.get(f"v_{NULO}_1", 0)
    origens["abstencao"] = d["aptos"] - tot1
    destinos = {f"f{n}": d[f"v_{n}_2"] for n in finalistas}
    destinos["brancos_nulos"] = d.get(f"v_{BRANCO}_2", 0) + d.get(f"v_{NULO}_2", 0)
    destinos["abstencao"] = d["aptos2"] - tot2

    peso = np.sqrt(d["aptos"].to_numpy(float))                 # seções grandes variam menos (em proporção)
    X = np.column_stack([origens[k].to_numpy(float) for k in origens]) / peso[:, None]
    Y = np.column_stack([destinos[k].to_numpy(float) for k in destinos]) / peso[:, None]
    mun = d.groupby(["uf", "cd_municipio"], observed=True).ngroup().to_numpy()
    ordem = np.argsort(mun, kind="stable")
    cortes = np.r_[0, np.cumsum(np.bincount(mun))]
    M, k, nd = len(cortes) - 1, X.shape[1], Y.shape[1]
    G, H = np.zeros((M, k, k)), np.zeros((M, k, nd))
    O, D = np.zeros((M, k)), np.zeros((M, nd))
    Xo, Yo = X[ordem], Y[ordem]
    Oraw = np.column_stack([origens[n].to_numpy(float) for n in origens])[ordem]
    Draw = np.column_stack([destinos[n].to_numpy(float) for n in destinos])[ordem]
    for m in range(M):
        a, b = cortes[m], cortes[m + 1]
        G[m], H[m] = Xo[a:b].T @ Xo[a:b], Xo[a:b].T @ Yo[a:b]
        O[m], D[m] = Oraw[a:b].sum(0), Draw[a:b].sum(0)
    uf_mun = d["uf"].astype(str).to_numpy()[ordem][cortes[:-1]]
    return {"uf": uf_mun, "G": G, "H": H, "O": O, "D": D, "origens": list(origens), "destinos": list(destinos)}


def estimar_fluxos(prep: dict, ufs: list[str] | None = None, n_boot: int = 0, seed: int = 1) -> dict:
    """
    Estima quantos eleitores de cada origem (1º turno) foram para cada destino (2º turno).
    Regressão ecológica: em cada seção, o que saiu para um destino é explicado pelo que cada
    origem tinha ali, com fluxos >= 0; depois os totais são fechados (IPF).
    Devolve {"F": votos [origem × destino], "lo"/"hi": intervalo 5%–95% (bootstrap por município, se n_boot)}.
    """
    sel = np.ones(len(prep["uf"]), bool) if not ufs else np.isin(prep["uf"], ufs)
    G, H, O, D = (prep[k][sel] for k in ("G", "H", "O", "D"))
    nd = H.shape[2]

    def _uma(idx):
        g, h = G[idx].sum(0), H[idx].sum(0)
        B = np.column_stack([_nnls_gram(g, h[:, j]) for j in range(nd)])
        o, de = O[idx].sum(0), D[idx].sum(0)
        return _fechar_totais(B * o[:, None], o, de)

    F = _uma(np.arange(len(G)))
    out = {"F": pd.DataFrame(F, index=prep["origens"], columns=prep["destinos"]),
           "municipios": int(sel.sum()), "secoes_origem": O.sum(0)}
    if n_boot and len(G) > 5:
        rng = np.random.default_rng(seed)
        reps = np.stack([_uma(rng.integers(0, len(G), len(G))) for _ in range(n_boot)])
        out["lo"] = pd.DataFrame(np.quantile(reps, .05, axis=0), index=prep["origens"], columns=prep["destinos"])
        out["hi"] = pd.DataFrame(np.quantile(reps, .95, axis=0), index=prep["origens"], columns=prep["destinos"])
    return out
