"""Constantes, carregadores de dados (com cache) e utilitários compartilhados pelas páginas do painel."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from analise import (BRANCO, NULO, comparar_turnos, estimar_fluxos, juntar_horario, limites_funil,
                     marcar_criterios, perfil_horario, pontuar_secoes, preparar_fluxo, resumo, resumo_coluna,
                     resumo_cruzamento, votos_por_hora)

PASTA = Path(__file__).resolve().parent.parent / "dados"
RESULTADOS = Path(__file__).resolve().parent.parent / "resultados"   # resultados pré-calculados, versionados no git
REPO_URL = "https://github.com/feumarinho/esteleicaocompared"
ORIGINAL_AUTOR = "Ricardo Albuquerque"
ORIGINAL_URL = "https://github.com/ralbuque/esteleicao"   # repositório de onde este projeto foi derivado (fork)
COR_ALTA, COR_BAIXA, COR_NORMAL = "#d6453d", "#2f6fb5", "#9aa4b1"
TODOS = "— Todos —"
NOMES_CURTOS = {13: "Lula", 22: "Flávio", 70: "Cury", 14: "Renan", 55: "Caiado", 30: "Zema"}


def arquivos_logs(caminho_secoes: Path) -> list[Path]:
    sufixo = caminho_secoes.stem.replace("secoes_", "")  # ex.: 2026_t1
    return sorted(PASTA.glob(f"logs_{sufixo}_*.parquet"))


# cache_resource: UMA cópia em memória compartilhada por todos os visitantes (a base tem ~600 MB;
# cache_data copiaria tudo a cada interação). O código nunca altera `base` no lugar.
# `assinatura` (nomes + datas dos arquivos) faz o cache recarregar quando chegam logs novos.
@st.cache_resource(show_spinner="Carregando e calculando estatísticas…", max_entries=2)
def carregar(caminho: str, assinatura: tuple, incluir_zz: bool) -> pd.DataFrame:
    df = pontuar_secoes(pd.read_parquet(caminho))
    arqs = arquivos_logs(Path(caminho))
    logs = pd.concat([pd.read_parquet(a) for a in arqs], ignore_index=True) if arqs else None
    df = juntar_horario(df, logs)
    if not incluir_zz:
        df = df[df["uf"].astype(str) != "ZZ"]
    # tipos compactos: menos memória no servidor
    for c in df.select_dtypes("float64").columns:
        df[c] = df[c].astype("float32")
    for c in df.select_dtypes("int64").columns:
        df[c] = pd.to_numeric(df[c], downcast="integer")
    for c in ["uf", "municipio", "nome_local", "endereco_local", "dia", "referencia", "transito"]:
        if c in df:
            df[c] = df[c].astype("category")
    # .copy() consolida as colunas num bloco contíguo; sem isso a base fica "fragmentada"
    # e cada visitante força o pandas a copiar tudo de novo a cada interação.
    df = df.reset_index(drop=True).copy()
    _devolver_memoria()
    return df


def arquivos_turnos(ano: str) -> dict[str, Path] | None:
    """Arquivos necessários para comparar os dois turnos, ou None se faltar algum."""
    a = {f"{k}{t}": PASTA / f"{k}_{ano}_t{t}.{ext}"
         for t in (1, 2) for k, ext in (("secoes", "parquet"), ("votos", "parquet"), ("candidatos", "json"))}
    return a if all(p.exists() for p in a.values()) else None


def candidatos_turnos(ano: str) -> dict[int, str]:
    """{número: nome} dos candidatos à Presidência que disputaram os dois turnos."""
    import json
    a = arquivos_turnos(ano)
    n1, n2 = (json.loads(a[f"candidatos{t}"].read_text(encoding="utf-8")) for t in (1, 2))
    return {int(n): n1[n] for n in n1 if n in n2 and int(n) not in (BRANCO, NULO)}


@st.cache_resource(show_spinner="Comparando os dois turnos…", max_entries=2)
def carregar_comparacao(ano: str, cand: int, assinatura: tuple, incluir_zz: bool) -> pd.DataFrame:
    a = arquivos_turnos(ano)
    s1, s2, v1, v2 = (pd.read_parquet(a[k]) for k in ("secoes1", "secoes2", "votos1", "votos2"))
    d = comparar_turnos(s1, s2, v1, v2, cand)
    if not incluir_zz:
        d = d[d["uf"].astype(str) != "ZZ"]
    for c in d.select_dtypes("float64").columns:
        d[c] = d[c].astype("float32")
    for c in ["uf", "municipio", "nome_local", "endereco_local", "referencia"]:
        if c in d:
            d[c] = d[c].astype("category")
    return d.reset_index(drop=True).copy()


def arquivo_risco(ano: str) -> Path:
    """Arquivo ESTÁTICO (vai no git) gerado por gerar_resultado_risco.py."""
    return RESULTADOS / f"risco_{ano}.parquet"


def candidatos_risco(ano: str) -> list[int]:
    import json
    return json.loads(arquivo_risco(ano).with_suffix(".json").read_text(encoding="utf-8"))["candidatos"]


@st.cache_resource(show_spinner="Carregando o cruzamento de risco…", max_entries=2)
def carregar_risco(ano: str, cand: int, assinatura: tuple) -> dict:
    """Seções do 1º turno com log (métricas dos três critérios) e desempenho do candidato no 2º turno.
    Lê o arquivo estático; em produção não baixa logs nem lê os .parquet de dados/."""
    import pyarrow.parquet as pq
    cols_f = pq.read_schema(arquivo_risco(ano)).names
    comum = [c for c in cols_f if not any(c.endswith(f"_{n}") for n in (13, 22)) or c.endswith(f"_{cand}")]
    d = pd.read_parquet(arquivo_risco(ano), columns=comum)
    d = d.rename(columns={f"{k}_{cand}": k for k in ("votos1", "votos2", "esperado_pp", "z_desvio")})
    d["uf"] = d["uf"].astype(str)
    d["pct1"] = d["votos1"] / d["validos1"]
    d["pct2"] = d["votos2"] / d["validos2"]
    d["delta_votos"] = d["votos2"] - d["votos1"]
    d["desvio_pp"] = d["pct2"] - d["esperado_pp"]
    d["votos_vs_esperado"] = d["votos2"] - d["esperado_pp"] * d["validos2"]
    for c in d.select_dtypes("float64").columns:
        d[c] = d[c].astype("float32")
    return {"mr": d.reset_index(drop=True).copy(), "n_ufs_log": int(d["uf"].nunique()),
            "n_ufs": 27, "tem_manual": "z_manual" in d}


@st.cache_resource(show_spinner="Preparando o fluxo de votos…", max_entries=2)
def carregar_fluxo(ano: str, assinatura: tuple, incluir_zz: bool) -> dict:
    a = arquivos_turnos(ano)
    s1, s2, v1, v2 = (pd.read_parquet(a[k]) for k in ("secoes1", "secoes2", "votos1", "votos2"))
    if not incluir_zz:
        s1, s2 = s1[s1["uf"].astype(str) != "ZZ"], s2[s2["uf"].astype(str) != "ZZ"]
    return preparar_fluxo(s1, s2, v1, v2, sorted(candidatos_turnos(ano)))


def _devolver_memoria():
    """Devolve ao sistema a memória temporária da carga (efeito no Linux; inofensivo no Windows/Mac)."""
    import ctypes
    import gc
    import sys
    gc.collect()
    if sys.platform.startswith("linux"):
        try:
            ctypes.CDLL("libc.so.6").malloc_trim(0)
        except Exception:
            pass


def filtrar(d: pd.DataFrame, mascara: pd.Series, colunas: list[str] | None = None) -> pd.DataFrame:
    """Filtra linhas sem copiar a base inteira quando a máscara é toda verdadeira."""
    if colunas is not None:
        return d.loc[mascara, list(dict.fromkeys(c for c in colunas if c in d))]
    return d if bool(mascara.all()) else d[mascara]


def com_log(d: pd.DataFrame) -> pd.DataFrame:
    """Seções com log. Se quase todas têm, devolve a própria base (sem copiar ~300 MB):
    nas seções sem log as colunas do log estão vazias (NaN) e ficam fora dos cálculos."""
    m = d["tem_log"].astype(bool)
    return d if m.mean() >= 0.9 else d[m]


def pct(x, casas=1):
    return "—" if pd.isna(x) else f"{x * 100:.{casas}f}%"


def hora(x):
    if pd.isna(x):
        return "—"
    m = int(round(x * 60))
    return f"{m // 60}h{m % 60:02d}"


# indicadores que podem ser cruzados: nome -> (coluna z com sinal "suspeito = positivo", coluna bruta, rótulo bruto)
CRITERIOS = {
    "Abstenção baixa": ("z_abst_baixa", "taxa_abstencao", "taxa de abstenção"),
    "Votação tardia": ("z_horario", "pct_apos_17", "% dos votos após 17h"),
    "Muitos sem digital": ("z_sem_digital", "pct_sem_digital", "% dos eleitores liberados sem digital"),
    "Liberação manual alta": ("z_manual", "pct_manual_cadastrados",
                              "% liberados pelo mesário (entre quem tem digital)"),
}
EIXO_Z = {
    "Abstenção baixa": "← abstenção mais ALTA · z da abstenção (invertido) · mais BAIXA →",
    "Votação tardia": "← votos mais cedo · z da hora média · mais tarde →",
    "Muitos sem digital": "← menos · z de eleitores sem digital · mais →",
    "Liberação manual alta": "← menos · z de liberação manual · mais →",
}


AMOSTRA_FUNDO = 15_000  # pontos "normais" desenhados nos gráficos de dispersão (os destacados vão todos)


def histograma(valores: pd.Series, n_bins: int, cor: str, log_y: bool = False) -> go.Figure:
    """Histograma calculado no servidor: envia ao navegador só as alturas das barras,
    não as ~500 mil seções (economiza memória e banda)."""
    v = pd.to_numeric(valores, errors="coerce").dropna().to_numpy(dtype=float)
    fig = go.Figure()
    if len(v):
        cont, bordas = np.histogram(v, bins=n_bins)
        centros, larg = (bordas[:-1] + bordas[1:]) / 2, np.diff(bordas)
        fig.add_trace(go.Bar(x=centros, y=cont, width=larg, marker_color=cor, marker_line_width=0,
                             hovertemplate="%{x:.3g}: %{y} seções<extra></extra>"))
    fig.update_layout(bargap=0, yaxis_type="log" if log_y else None)
    return fig


def amostrar_fundo(d: pd.DataFrame, destaque: pd.Series) -> pd.DataFrame:
    """Todos os pontos destacados + uma amostra dos demais (fundo cinza)."""
    fundo = d[~destaque]
    if len(fundo) > AMOSTRA_FUNDO:
        fundo = fundo.sample(AMOSTRA_FUNDO, random_state=1)
    return pd.concat([fundo, d[destaque]])


def linha_df(s: pd.Series) -> pd.DataFrame:
    """Uma seção (Series) como DataFrame com tipos numéricos corretos."""
    return pd.DataFrame([s]).infer_objects()


def _mi(x: float) -> str:
    return f"{x / 1e6:,.2f} mi".replace(",", "X").replace(".", ",").replace("X", ".") if abs(x) >= 1e5 \
        else f"{x / 1e3:,.0f} mil".replace(",", ".")


def _pt(x: float, casas: int = 0) -> str:
    return f"{x:,.{casas}f}".replace(",", "X").replace(".", ",").replace("X", ".")
