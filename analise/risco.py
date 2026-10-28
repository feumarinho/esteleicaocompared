"""Seções de risco do 1º turno (três critérios do painel original) e cruzamento com o desempenho."""
from __future__ import annotations

import numpy as np
import pandas as pd


def marcar_criterios(d: pd.DataFrame, medida: str = "z_ajustado", limite: float = 3.0, min_aptos: int = 50,
                     lim_17: float = 0.15, so_destoa: bool = True) -> tuple[pd.Series, pd.Series, pd.Series]:
    """
    Os três critérios do painel, cada um independente (devolve três máscaras booleanas):
      abstenção baixa:   `medida` <= -limite e pelo menos `min_aptos` aptos;
      voto após 17h:     >= lim_17 dos votos e >= 10 votos; se so_destoa, só conta quando a hora média da seção
                         é 30+ min mais tarde que a das outras seções da mesma escola (escola inteira tarde = fila);
      liberação manual:  z_manual >= limite e pelo menos 5 casos.
    """
    f_abst = (d[medida] <= -limite) & (d["aptos"] >= min_aptos)
    if "votos_apos_17" in d:
        f_17 = (d["pct_apos_17"] >= lim_17) & (d["votos_apos_17"] >= 10)
        if so_destoa and "dif_local_min" in d:
            f_17 &= (d["dif_local_min"] >= 30) | d["dif_local_min"].isna()
        f_17 = f_17.fillna(False).astype(bool)
    else:
        f_17 = pd.Series(False, index=d.index)
    if "z_manual" in d:
        f_man = ((d["z_manual"] >= limite) & (d["votos_manual"] >= 5)).fillna(False).astype(bool)
    else:
        f_man = pd.Series(False, index=d.index)
    return f_abst.fillna(False).astype(bool), f_17, f_man


def resumo_cruzamento(d: pd.DataFrame, grupos: dict[str, pd.Series]) -> pd.DataFrame:
    """
    Desempenho de um candidato (colunas de `comparar_turnos`) em cada grupo de seções.

    pct1/pct2: % dos votos válidos do grupo (soma dos votos ÷ soma dos válidos);
    desvio_pp: quanto o candidato teve a mais (+) ou a menos (−) que o esperado pelo município, em p.p.
               do grupo (soma de votos × esperado ÷ soma dos válidos do 2º turno);
    z_medio ± ic: média do z do desvio com intervalo de 95%. Com z calibrado (desvio padrão ≈ 1), z_medio ≈ 0
               significa que o grupo se comporta como o resto.
    """
    linhas = []
    for nome, m in grupos.items():
        g = d[m]
        n = len(g)
        z = g["z_desvio"].dropna()
        v1, q1, v2, q2 = g["votos1"].sum(), g["validos1"].sum(), g["votos2"].sum(), g["validos2"].sum()
        linhas.append({
            "grupo": nome, "secoes": n,
            "pct1": v1 / q1 if q1 else np.nan, "pct2": v2 / q2 if q2 else np.nan,
            "variacao_pp": (v2 / q2 - v1 / q1) * 100 if q1 and q2 else np.nan,
            "desvio_pp": g["votos_vs_esperado"].sum() / q2 * 100 if q2 else np.nan,
            "votos_vs_esperado": g["votos_vs_esperado"].sum(),
            "z_medio": z.mean() if len(z) else np.nan,
            "ic": 1.96 * z.std(ddof=1) / np.sqrt(len(z)) if len(z) > 1 else np.nan,
            "pct_melhora": (z >= 3).mean() if len(z) else np.nan,
            "pct_piora": (z <= -3).mean() if len(z) else np.nan,
        })
    return pd.DataFrame(linhas)
