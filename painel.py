"""
Painel de abstenção e horário de votação por seção eleitoral.
    streamlit run painel.py
"""
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

st.set_page_config(page_title="Abstenção por seção", page_icon="🗳️", layout="wide")
PASTA = Path(__file__).parent / "dados"
RESULTADOS = Path(__file__).parent / "resultados"   # resultados pré-calculados, versionados no git
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
            "n_ufs": 26 + 1, "tem_manual": "z_manual" in d}


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


# ---------------------------------------------------------------- dados
arquivos = sorted(PASTA.glob("secoes_*.parquet"), reverse=True)
if not arquivos:
    st.error("Nenhum dado encontrado. Rode primeiro:  `python baixar_dados.py`")
    st.stop()

with st.sidebar:
    st.header("🗳️ Abstenção por seção")
    arquivo = st.selectbox("Eleição / turno", arquivos, format_func=lambda p: p.stem.replace("secoes_", ""))
    st.subheader("Navegação")
    incluir_zz = st.checkbox("Incluir exterior (ZZ)", value=False)
    assinatura = tuple((a.name, a.stat().st_mtime) for a in [arquivo, *arquivos_logs(arquivo)])
    base = carregar(str(arquivo), assinatura, incluir_zz)
    tem_logs = bool(base["tem_log"].any())

    ufs = sorted(base["uf"].unique().tolist())
    uf = st.selectbox("Estado", [TODOS] + ufs)
    df = base if uf == TODOS else base[base["uf"] == uf]

    mun = zona = secao = TODOS
    if uf != TODOS:
        muns = df[["cd_municipio", "municipio"]].drop_duplicates().sort_values("municipio")
        opc = dict(zip(muns["cd_municipio"], muns["municipio"]))
        mun = st.selectbox("Município", [TODOS] + list(opc), format_func=lambda c: opc.get(c, c))
        if mun != TODOS:
            df = df[df["cd_municipio"] == mun]
            zona = st.selectbox("Zona", [TODOS] + sorted(df["zona"].dropna().unique().tolist()))
            if zona != TODOS:
                df = df[df["zona"] == zona]
                secao = st.selectbox("Seção", [TODOS] + sorted(df["secao"].dropna().unique().tolist()))

    st.subheader("Sinalização")
    st.caption("Uma seção é sinalizada por cada critério abaixo que ela cumprir.")
    st.markdown("**🔻 Abstenção baixa**")
    medida = st.radio("Medida", ["z_ajustado", "z_binomial", "z_simples"],
                      format_func={"z_ajustado": "z ajustado (recomendado)",
                                   "z_binomial": "z binomial",
                                   "z_simples": "z simples (média/desvio)"}.get,
                      help="Ver README: o z ajustado leva em conta o tamanho da seção "
                           "e a variação natural entre seções.")
    limite = st.slider("Abstenção abaixo do esperado em ≥ (desvios)", 2.0, 6.0, 3.0, 0.5,
                       help="Também usado para a liberação manual (z ≥ este valor).")
    min_aptos = st.number_input("Ignorar seções com menos aptos que", 0, 500, 50, 10)
    if tem_logs:
        st.markdown("**⏰ Voto após 17h**")
        lim_17 = st.slider("% dos votos depois das 17h ≥", 5, 50, 15, 5,
                           help="Mínimo de 10 votos após as 17h.") / 100
        so_destoa = st.checkbox("Só se a seção destoar da própria escola", value=True,
                                help="Exige hora média 30+ min mais tarde que as outras seções do mesmo "
                                     "local. Quando a escola inteira vota tarde, quase sempre é fila.")
        st.markdown("**🖐️ Liberação manual pelo mesário**")
        st.caption("Eleitores COM digital cadastrada liberados pelo mesário: z ≥ limite acima e "
                   "pelo menos 5 casos.")
        min_crit = st.radio("Mostrar seções que cumprem", [1, 2, 3], horizontal=True,
                            format_func=lambda n: {1: "≥ 1 critério", 2: "≥ 2", 3: "os 3"}[n])
    else:
        lim_17, so_destoa, min_crit = 0.15, True, 1

    st.subheader("Cruzamento de indicadores")
    tem_digital = "z_sem_digital" in base
    disponiveis = [c for c in CRITERIOS if c in ("Abstenção baixa", "Votação tardia") or tem_digital]
    if tem_logs:
        criterios = st.multiselect(
            "Critérios que precisam valer AO MESMO TEMPO", disponiveis,
            default=["Abstenção baixa", "Votação tardia"],
            help="Cada critério é um z comparando a seção com o próprio município. O score cruzado "
                 "é o MENOR deles: só é alto se a seção for extrema em todos os critérios escolhidos.")
        criterios = criterios or ["Abstenção baixa"]
        limite_cruz = st.slider("Destacar quando todos os critérios ≥", 1.0, 6.0, 2.0, 0.5,
                                help="Com 2, a seção precisa estar 2 desvios além do esperado em cada critério.")
        n_ufs_log = base.loc[base["tem_log"], "uf"].nunique()
        st.caption(f"Logs carregados para {n_ufs_log} UF(s): "
                   f"{int(base['tem_log'].sum()):,} seções.".replace(",", "."))
        if not tem_digital:
            st.caption("⚠️ Logs processados por uma versão antiga, sem dados de digital. "
                       "Rode `python baixar_logs.py --refazer`.")
    else:
        criterios, limite_cruz = ["Abstenção baixa", "Votação tardia"], 2.0
        st.caption("Sem logs de urna. Rode `python baixar_logs.py --ufs AC` (por exemplo).")


def calcular_score(d: pd.DataFrame) -> pd.Series:
    zs = [d[CRITERIOS[c][0]] for c in criterios if CRITERIOS[c][0] in d]
    return pd.concat(zs, axis=1).min(axis=1, skipna=False) if zs else pd.Series(np.nan, index=d.index)


base = base.assign(z_abst_baixa=-base["z_ajustado"])
base = base.assign(score_cruzado=calcular_score(base))
df = df.assign(z_abst_baixa=-df["z_ajustado"])
df = df.assign(score_cruzado=calcular_score(df))
NOME_CRUZ = " + ".join(c.lower() for c in criterios)

def sinalizar(d: pd.DataFrame) -> pd.DataFrame:
    """Marca os três critérios de interesse e conta quantos cada seção cumpre."""
    f_abst, f_17, f_man = marcar_criterios(d, medida, limite, min_aptos, lim_17, so_destoa)
    n = f_abst.astype(int) + f_17.astype(int) + f_man.astype(int)
    rot = pd.Series("", index=d.index, dtype=object)
    alguma = n > 0
    if alguma.any():  # monta o texto só para as poucas seções que cumprem algum critério
        partes = pd.concat([f_abst[alguma].map({True: "abstenção baixa", False: ""}),
                            f_17[alguma].map({True: "voto após 17h", False: ""}),
                            f_man[alguma].map({True: "liberação manual", False: ""})], axis=1)
        rot[alguma] = partes.apply(lambda r: " · ".join(x for x in r if x), axis=1)
    return d.assign(f_abst=f_abst, f_17=f_17, f_man=f_man, n_criterios=n, criterios_cumpridos=rot,
                    alerta=np.where(n >= min_crit, "sinalizada", "normal"))


df = sinalizar(df)

# ---------------------------------------------------------------- cabeçalho
nivel = ("Brasil" if uf == TODOS else uf if mun == TODOS else
         f"{df['municipio'].iloc[0]} / {uf}" + (f" · Zona {zona}" if zona != TODOS else ""))
st.title(nivel)
st.caption("Fonte: dados abertos do TSE (resultados por seção e logs das urnas). Seções sinalizadas são "
           "**desvios estatísticos** em relação ao próprio município, não prova de irregularidade: a maioria "
           "tem explicação comum (fila, perfil do eleitorado, cadastro biométrico, leitor com defeito). "
           "Veja \"Como ler este painel\" abaixo.")
with st.expander("ℹ️ Como ler este painel"):
    st.markdown(
        "- **Abstenção baixa**: abstenção abaixo do esperado para o município, levando em conta o tamanho da "
        "seção e a variação natural entre seções (z ajustado).\n"
        "- **Voto após 17h**: é permitido — quem está na fila às 17h vota. Fica sinalizado quando uma parte "
        "grande dos votos é depois das 17h e a seção destoa das outras da mesma escola.\n"
        "- **Liberação manual**: eleitor com digital cadastrada que não foi reconhecida e foi liberado pelo "
        "mesário. Acontece com idosos, digitais gastas e leitores sujos ou com defeito.\n"
        "- Com cerca de 470 mil seções, dezenas a centenas aparecem como extremas só por acaso. Para "
        "investigar um caso, compare com as outras seções da mesma escola, consulte o boletim de urna e o "
        "log da seção no site do TSE e, se houver dúvida, procure o TRE do estado.")

r = resumo(df).iloc[0]
c = st.columns(7)
c[0].metric("Seções", f"{int(r.secoes):,}".replace(",", "."))
c[1].metric("Aptos", f"{r.aptos / 1e6:,.2f} mi".replace(".", ",") if r.aptos >= 1e6 else f"{int(r.aptos):,}".replace(",", "."))
c[2].metric("Abstenção agregada", pct(r.taxa_agregada, 2),
            help="Total de abstenções ÷ total de aptos (número oficial)")
c[3].metric("Média das seções", pct(r.media),
            help="Média simples da taxa de abstenção de cada seção")
c[4].metric("Desvio padrão", pct(r.desvio_padrao),
            help="Desvio padrão da taxa de abstenção entre as seções")
c[5].metric("🔻 Abstenção baixa", int(df["f_abst"].sum()),
            help=f"Seções com {medida} ≤ −{limite} e ≥ {min_aptos} aptos")
c[6].metric("🚩 Sinalizadas", int((df["alerta"] == "sinalizada").sum()),
            help=f"Seções que cumprem pelo menos {min_crit} dos critérios: abstenção baixa, "
                 "voto após 17h, liberação manual")

dl = com_log(df)
if len(dl):
    c = st.columns(7)
    n_com_log = int(dl["tem_log"].astype(bool).sum())
    c[0].metric("Seções com log", f"{n_com_log:,}".replace(",", "."))
    c[1].metric("Hora média", hora((dl["hora_media"] * dl["votos_log"]).sum() / dl["votos_log"].sum()),
                help="Média ponderada pelo número de votos, em horário de Brasília (8h–17h)")
    c[2].metric("Desvio (seções)", f"{dl['hora_media'].std() * 60:.0f} min",
                help="Desvio padrão da hora média de cada seção")
    c[3].metric("Votos após 17h", pct(dl["votos_apos_17"].sum() / dl["votos_log"].sum(), 2))
    c[4].metric("Seções c/ voto 17h+", pct((dl["votos_apos_17"] > 0).sum() / max(n_com_log, 1)))
    c[5].metric("Corr. abst. × hora", f"{dl['taxa_abstencao'].rank().corr(dl['hora_media'].rank()):+.2f}",
                help="Spearman entre taxa de abstenção e hora média. Negativo = onde se falta menos, "
                     "vota-se mais tarde (esperado: mais eleitores → mais fila).")
    c[6].metric("⚠️ Cruzamento", int((dl["score_cruzado"] >= limite_cruz).sum()),
                help=f"Seções com {NOME_CRUZ} (todos ≥ {limite_cruz} desvios)")
    if "votos_digital" in dl:
        tot = dl["votos_log"].sum()
        c = st.columns(7)
        c[0].metric("Sem digital", pct(1 - dl["votos_digital"].sum() / tot),
                    help="% dos eleitores liberados sem reconhecimento da digital (sem cadastro + manual)")
        c[1].metric("↳ sem cadastro", pct(dl["votos_sem_cadastro"].sum() / tot),
                    help="Eleitor não tem digital cadastrada na Justiça Eleitoral")
        c[2].metric("↳ liberação manual", pct(dl["votos_manual"].sum() / tot),
                    help="Eleitor TEM digital cadastrada, ela não foi reconhecida em 4 tentativas e o "
                         "mesário liberou o voto com a digital dele")
        c[3].metric("Desvio (seções)", f"{dl['pct_sem_digital'].std() * 100:.1f} p.p.",
                    help="Desvio padrão do % sem digital entre as seções")
        c[4].metric("Corr. abst. × sem digital",
                    f"{dl['taxa_abstencao'].rank().corr(dl['pct_sem_digital'].rank()):+.2f}",
                    help="Spearman entre abstenção e % sem digital, seção a seção")
        c[5].metric("🖐️ z ≥ 3 sem digital", int((dl["z_sem_digital"] >= 3).sum()))
        c[6].metric("🖐️ z ≥ 3 manual", int((dl["z_manual"] >= 3).sum()))


# ---------------------------------------------------------------- detalhe de seção
def detalhe_secao(s: pd.Series):
    st.subheader(f"Seção {s['secao']} · Zona {s['zona']} · {s['municipio']}/{s['uf']}")
    if "nome_local" in s and pd.notna(s.get("nome_local")):
        st.caption(f"Local de votação: {s['nome_local']}"
                   + (f" — {s['endereco_local']}" if pd.notna(s.get('endereco_local')) else ""))
    k = st.columns(5)
    k[0].metric("Abstenção da seção", pct(s["taxa_abstencao"]),
                f"{(s['taxa_abstencao'] - s['taxa_esperada']) * 100:+.1f} p.p. vs esperado",
                delta_color="inverse")
    k[1].metric("Aptos / faltaram", f"{s['aptos']} / {s['abstencoes']}",
                f"esperado ≈ {s['abst_esperadas']:.0f}", delta_color="off")
    k[2].metric("z ajustado", f"{s['z_ajustado']:+.2f}")
    k[3].metric("Percentil no município", pct(s["pct_municipio"], 0))
    k[4].metric("Percentil no Brasil", pct(s["pct_brasil"], 0))

    zona_df = base[(base["cd_municipio"] == s["cd_municipio"]) & (base["zona"] == s["zona"])]
    mun_df = base[base["cd_municipio"] == s["cd_municipio"]]
    uf_tx = base.loc[base["uf"] == s["uf"], "taxa_abstencao"]
    comp = pd.DataFrame({
        "nível": ["Esta seção", f"Zona {s['zona']}", "Município", s["uf"], "Brasil"],
        "media": [s["taxa_abstencao"]] + [x.mean() for x in (zona_df["taxa_abstencao"], mun_df["taxa_abstencao"],
                                                             uf_tx, base["taxa_abstencao"])],
        "dp": [0] + [x.std() for x in (zona_df["taxa_abstencao"], mun_df["taxa_abstencao"],
                                       uf_tx, base["taxa_abstencao"])],
    })
    a, b = st.columns(2)
    fig = go.Figure(go.Bar(x=comp["nível"], y=comp["media"],
                           error_y=dict(type="data", array=comp["dp"], visible=True),
                           marker_color=[COR_ALTA if s["z_ajustado"] > 0 else COR_BAIXA] + [COR_NORMAL] * 4,
                           text=[pct(v) for v in comp["media"]], textposition="outside"))
    fig.update_layout(title="Comparação (barra = média, traço = ± 1 desvio padrão)",
                      yaxis_tickformat=".0%", height=360, margin=dict(t=50, b=10))
    a.plotly_chart(fig, width="stretch")

    fig = px.histogram(mun_df, x="taxa_abstencao", nbins=40, color_discrete_sequence=[COR_NORMAL],
                       title="Onde a seção cai entre as seções do município")
    fig.add_vline(x=s["taxa_abstencao"], line_color=COR_ALTA, line_width=3,
                  annotation_text="esta seção")
    fig.update_layout(xaxis_tickformat=".0%", height=360, margin=dict(t=50, b=10),
                      xaxis_title="taxa de abstenção", yaxis_title="seções")
    b.plotly_chart(fig, width="stretch")

    vizinhas = None
    if "local" in s and pd.notna(s.get("local")):
        vizinhas = mun_df[(mun_df["zona"] == s["zona"]) & (mun_df["local"] == s["local"])]

    if s.get("tem_log", False):
        st.markdown("#### ⏰ Horário dos votos (log da urna)")
        k = st.columns(6)
        k[0].metric("Hora média", hora(s["hora_media"]),
                    f"{(s['hora_media'] - mun_df['hora_media'].median()) * 60:+.0f} min vs município",
                    delta_color="inverse")
        k[1].metric("Votos após 17h", f"{int(s['votos_apos_17'])}  ({pct(s['pct_apos_17'])})")
        k[2].metric("Último voto", hora(s["ultimo_voto"]))
        k[3].metric("Sem biometria após 17h", pct(s["pct_sem_bio_apos_17"], 0),
                    f"{pct(s['pct_sem_bio'], 0)} no dia todo", delta_color="off")
        k[4].metric("z horário", f"{s['z_horario']:+.2f}" if pd.notna(s["z_horario"]) else "—")
        k[5].metric("Score cruzado", f"{s['score_cruzado']:+.2f}" if pd.notna(s.get("score_cruzado")) else "—",
                    help=f"Critérios: {NOME_CRUZ}")
        if s.get("sinais"):
            st.warning("**Sinais no log:** " + s["sinais"])

        perfis = {"Esta seção": perfil_horario(linha_df(s))}
        if vizinhas is not None:
            outras = vizinhas[vizinhas["secao"] != s["secao"]]
            if outras["tem_log"].any():
                perfis["Outras seções da escola"] = perfil_horario(outras)
        perfis["Município"] = perfil_horario(mun_df)
        fig = go.Figure()
        for (nome, p), cor in zip(perfis.items(), [COR_ALTA, "#33415c", COR_NORMAL]):
            p = p[(p.index >= 6) & (p.index <= 23)]
            fig.add_trace(go.Bar(x=[f"{h}h" for h in p.index], y=p.values, name=nome, marker_color=cor))
        fig.add_vline(x=10.5, line_dash="dash", line_color="black", annotation_text="17h encerramento")
        fig.update_layout(barmode="group", yaxis_tickformat=".0%", height=380, margin=dict(t=40, b=10),
                          title="% dos votos em cada hora (horário de Brasília)", legend=dict(orientation="h"))
        st.plotly_chart(fig, width="stretch")
        st.caption(f"Abertura da urna: {hora(s['abertura'])} · primeiro voto {hora(s['primeiro_voto'])} · "
                   f"maior intervalo sem votos entre 16h e 17h: {s['ociosa_antes_17_min']:.0f} min · "
                   f"votos no log: {int(s['votos_log'])} (comparecimento oficial: {int(s['comparecimento'])}) · "
                   f"urnas usadas: {int(s['n_urnas'])}")

    if s.get("tem_log", False) and pd.notna(s.get("votos_digital")):
        st.markdown("#### 🖐️ Identificação do eleitor")
        n = int(s["votos_log"])
        k = st.columns(5)
        k[0].metric("Sem digital", pct(s["pct_sem_digital"]),
                    f"{(s['pct_sem_digital'] - s['sem_digital_esperado']) * 100:+.1f} p.p. vs esperado",
                    delta_color="inverse")
        k[1].metric("Sem cadastro de digital", f"{int(s['votos_sem_cadastro'])} ({pct(s['pct_sem_cadastro'])})")
        k[2].metric("Liberação manual", f"{int(s['votos_manual'])} ({pct(s['pct_manual_cadastrados'])})",
                    f"esperado ≈ {pct(s['manual_esperado'])} de quem tem digital", delta_color="off")
        k[3].metric("Maior sequência manual", int(s["maior_seq_manual"]),
                    help="Maior número de eleitores seguidos liberados manualmente pelo mesário")
        k[4].metric("z sem digital / z manual", f"{s['z_sem_digital']:+.1f} / {s['z_manual']:+.1f}"
                    if pd.notna(s["z_sem_digital"]) else "—")
        um = linha_df(s)
        tot, sd, man = (votos_por_hora(um, p) for p in "hsm")
        faixa = [h for h in range(6, 24) if tot[h] > 0]
        if faixa:
            horas_ = list(range(min(faixa), max(faixa) + 1))
            fig = go.Figure()
            for nome, serie, cor in [("digital", tot - sd, "#9aa4b1"), ("sem cadastro", sd - man, "#e0a33a"),
                                     ("liberação manual", man, COR_ALTA)]:
                fig.add_trace(go.Bar(x=[f"{h}h" for h in horas_], y=[serie[h] for h in horas_], name=nome,
                                     marker_color=cor))
            fig.update_layout(barmode="stack", height=340, margin=dict(t=40, b=10), legend=dict(orientation="h"),
                              title=f"Como cada eleitor foi liberado, hora a hora ({n} votos)",
                              yaxis_title="votos")
            st.plotly_chart(fig, width="stretch")

    if vizinhas is not None:
        st.markdown("**Outras seções do mesmo local de votação** (mesma escola, mesmo público — "
                    "se só esta destoa, é um sinal mais forte)")
        cols_v = ["secao", "aptos", "abstencoes", "taxa_abstencao", "z_ajustado"]
        if vizinhas["tem_log"].any():
            cols_v += ["hora_media", "pct_apos_17", "ultimo_voto", "z_horario"]
            if "pct_sem_digital" in vizinhas:
                cols_v += ["pct_sem_digital", "pct_sem_cadastro", "pct_manual_cadastrados", "z_manual"]
        st.dataframe(vizinhas[cols_v].sort_values("secao"), hide_index=True, width="stretch",
                     column_config={**{c: st.column_config.NumberColumn(format="percent")
                                       for c in ["taxa_abstencao", "pct_apos_17", "pct_sem_bio_apos_17",
                                                 "pct_sem_digital", "pct_sem_cadastro", "pct_manual_cadastrados"]},
                                    **{c: st.column_config.NumberColumn(format="%.2f")
                                       for c in ["z_ajustado", "z_horario", "hora_media", "ultimo_voto",
                                                 "z_manual"]}})


if secao != TODOS:
    detalhe_secao(df[df["secao"] == secao].iloc[0])
    st.stop()

# ---------------------------------------------------------------- abas
(aba_comp, aba_dist, aba_funil, aba_alertas, aba_hora, aba_dig, aba_cruz, aba_turnos, aba_fluxo,
 aba_origem, aba_risco) = st.tabs(
    ["📊 Comparar", "📈 Distribuição", "🔻 Funil", "🚩 Sinalizadas",
     "⏰ Horário dos votos", "🖐️ Sem digital", "🔀 Cruzamento", "🔁 1º × 2º turno", "🧭 Fluxo de votos",
     "🗳️ De onde vêm os votos", "🎯 Risco × melhora"])

if uf == TODOS:
    filho, rotulo = ["uf"], "uf"
elif mun == TODOS:
    filho, rotulo = ["cd_municipio", "municipio"], "municipio"
elif zona == TODOS:
    filho, rotulo = ["zona"], "zona"
else:
    filho, rotulo = (["local"], "local") if "local" in df else (["secao"], "secao")

with aba_comp:
    tab = resumo(df, filho)
    alertas = df[df["alerta"] == "sinalizada"].groupby(filho, observed=True).size().rename("sinalizadas")
    tab = tab.merge(alertas, left_on=filho, right_index=True, how="left").fillna({"sinalizadas": 0})
    tab[rotulo] = tab[rotulo].astype(str)

    if len(tab) <= 40:
        t = tab.sort_values("media")
        fig = go.Figure(go.Scatter(
            x=t["media"], y=t[rotulo], mode="markers",
            error_x=dict(type="data", array=t["desvio_padrao"].fillna(0), color="#b8c0cc"),
            marker=dict(size=9, color="#33415c"),
            customdata=np.stack([t["secoes"], t["taxa_agregada"]], axis=1),
            hovertemplate="%{y}<br>média %{x:.1%}<br>seções %{customdata[0]}<br>"
                          "agregada %{customdata[1]:.1%}<extra></extra>"))
        fig.add_vline(x=r.media, line_dash="dash", annotation_text="média do nível acima")
        fig.update_layout(title="Média ± 1 desvio padrão da abstenção das seções",
                          xaxis_tickformat=".0%", height=max(350, 22 * len(t) + 80),
                          margin=dict(l=10, r=10, t=50, b=10))
    else:
        fig = px.scatter(tab, x="media", y="desvio_padrao", size="aptos", color="sinalizadas",
                         hover_name=rotulo, color_continuous_scale="OrRd", size_max=40,
                         hover_data={"secoes": True, "taxa_agregada": ":.1%", "aptos": ":,"},
                         title="Cada ponto é uma unidade: média × desvio padrão "
                               "(longe do grupo = comportamento diferente)")
        fig.update_layout(xaxis_tickformat=".0%", yaxis_tickformat=".0%", height=560)
    st.plotly_chart(fig, width="stretch")

    st.dataframe(tab.drop(columns=[c for c in ["cd_municipio"] if c in tab and rotulo != "cd_municipio"])
                 .sort_values("media", ascending=False), hide_index=True, width="stretch",
                 column_config={c: st.column_config.NumberColumn(format="percent")
                                for c in ["taxa_agregada", "media", "desvio_padrao", "mediana",
                                          "mad", "p05", "p95", "minimo", "maximo"]})

with aba_dist:
    fig = histograma(df["taxa_abstencao"], 80, "#33415c")
    for k, estilo in [(0, "solid"), (1, "dash"), (-1, "dash"), (2, "dot"), (-2, "dot")]:
        x = r.media + k * r.desvio_padrao
        fig.add_vline(x=x, line_dash=estilo, line_color=COR_ALTA if k else "black",
                      annotation_text="média" if k == 0 else f"{k:+d} dp")
    fig.update_layout(title="Distribuição da abstenção por seção", xaxis_tickformat=".0%",
                      xaxis_title="taxa de abstenção", yaxis_title="seções", height=480)
    st.plotly_chart(fig, width="stretch")
    st.caption("A distribuição real tem caudas mais largas que uma normal; por isso, contar "
               "seções além de ±2 dp num nível grande (Brasil, UF) sempre dá milhares de casos. "
               "O z ajustado, comparando cada seção com o próprio município, é mais útil para achar pontos.")

with aba_funil:
    pontos = df[["aptos", "taxa_abstencao", "municipio", "zona", "secao"]].assign(
        _grupo=np.where(df["f_abst"], "abstenção baixa", "demais"))
    pontos = amostrar_fundo(pontos, pontos["_grupo"] != "demais")
    fig = go.Figure()
    for nome, cor in [("demais", COR_NORMAL), ("abstenção baixa", COR_BAIXA)]:
        d = pontos[pontos["_grupo"] == nome]
        fig.add_trace(go.Scattergl(
            x=d["aptos"], y=d["taxa_abstencao"], mode="markers", name=nome,
            marker=dict(size=4 if nome == "demais" else 7, color=cor,
                        opacity=0.35 if nome == "demais" else 0.9),
            text=d["municipio"].astype(str) + " · Z" + d["zona"].astype(str) + " · S" + d["secao"].astype(str),
            hovertemplate="%{text}<br>aptos %{x}<br>abstenção %{y:.1%}<extra></extra>"))
    tau2 = float(df["tau2"].median())
    for k, estilo in [(2, "dash"), (3, "solid")]:
        lim = limites_funil(r.taxa_agregada, tau2, int(df["aptos"].max()), k)
        for lado in ["inf", "sup"]:
            fig.add_trace(go.Scatter(x=lim["aptos"], y=lim[lado], mode="lines", showlegend=False,
                                     line=dict(color="black", dash=estilo, width=1), hoverinfo="skip"))
    fig.update_layout(title="Funil: seções pequenas variam mais por acaso — "
                            "linhas = ±2 e ±3 desvios esperados para cada tamanho",
                      xaxis_title="eleitores aptos na seção", yaxis_title="abstenção",
                      yaxis_tickformat=".0%", height=600)
    st.plotly_chart(fig, width="stretch")
    st.caption("O funil usa a abstenção agregada deste nível como centro. A cor (abstenção baixa) "
               "usa a comparação com o próprio município, por isso alguns pontos coloridos "
               "ficam dentro das linhas e vice-versa.")

with aba_alertas:
    sel = df[df["alerta"] == "sinalizada"].copy()
    # gravidade: soma do quanto a seção passa de cada critério
    grav = (-sel[medida]).clip(lower=0)
    if "z_manual" in sel:
        grav = grav + sel["z_manual"].clip(lower=0).fillna(0)
    if "pct_apos_17" in sel:
        grav = grav + (sel["pct_apos_17"].fillna(0) / max(lim_17, 1e-9)) * limite
    sel = sel.assign(gravidade=grav).sort_values(["n_criterios", "gravidade"], ascending=False)
    k = st.columns(4)
    k[0].metric("🔻 Abstenção baixa", int(df["f_abst"].sum()))
    k[1].metric("⏰ Voto após 17h", int(df["f_17"].sum()) if tem_logs else "—")
    k[2].metric("🖐️ Liberação manual", int(df["f_man"].sum()) if tem_logs else "—")
    k[3].metric("Cumprem 2 ou 3 critérios", int((df["n_criterios"] >= 2).sum()))
    sem_log = int((~df.loc[df["alerta"] == "sinalizada", "tem_log"]).sum()) if "tem_log" in df else 0
    st.write(f"**{len(sel):,}** seções cumprem pelo menos {min_crit} critério(s) (de {len(df):,}). "
             "Ordenadas pelo número de critérios e, depois, pela gravidade. Selecione uma linha para "
             "ver o detalhe." + (f" {sem_log:,} delas são de UFs sem logs baixados, onde só a abstenção "
                                 "pôde ser avaliada." if sem_log else ""))
    cols = [c for c in ["uf", "municipio", "zona", "secao", "n_criterios", "criterios_cumpridos",
                        "taxa_abstencao", "taxa_esperada", "z_ajustado", "votos_apos_17", "pct_apos_17",
                        "dif_local_min", "votos_manual", "pct_manual_cadastrados", "manual_esperado",
                        "z_manual", "maior_seq_manual", "sinais", "aptos", "nome_local"] if c in sel]
    if medida != "z_ajustado":
        cols.insert(cols.index("z_ajustado") + 1, medida)
    evento = st.dataframe(
        sel[cols], hide_index=True, width="stretch", height=460,
        on_select="rerun", selection_mode="single-row",
        column_config={**{c: st.column_config.NumberColumn(format="percent")
                          for c in ["taxa_abstencao", "taxa_esperada", "pct_apos_17",
                                    "pct_manual_cadastrados", "manual_esperado"]},
                       **{c: st.column_config.NumberColumn(format="%.2f")
                          for c in ["z_ajustado", "z_binomial", "z_simples", "z_manual"]},
                       "dif_local_min": st.column_config.NumberColumn(format="%+.0f min"),
                       "n_criterios": st.column_config.NumberColumn("critérios", format="%d")})
    st.download_button("⬇️ Baixar lista (CSV)", sel[cols].to_csv(index=False, sep=";", decimal=",")
                       .encode("utf-8-sig"), "secoes_sinalizadas.csv", "text/csv")
    linhas = evento.selection.rows if evento and evento.selection else []
    if linhas:
        st.divider()
        detalhe_secao(sel.iloc[linhas[0]])

# ---------------------------------------------------------------- horário dos votos
SEM_LOGS = ("Ainda não há logs de urna para este nível. Baixe e processe os logs do(s) estado(s):\n\n"
            "```\npython baixar_logs.py --ufs AC\n```\n"
            "Depois recarregue o painel. Comece por um estado pequeno: os arquivos do TSE são grandes.")

with aba_hora:
    dh = com_log(df)
    if dh.empty:
        st.info(SEM_LOGS)
    else:
        perfil = perfil_horario(dh)
        perfil_br = perfil_horario(base)
        perfil, perfil_br = [p[(p.index >= 7) & (p.index <= 23)] for p in (perfil, perfil_br)]
        fig = go.Figure()
        fig.add_trace(go.Bar(x=perfil.index, y=perfil.values, name=nivel,
                             marker_color=["#33415c" if h < 17 else COR_ALTA for h in perfil.index]))
        if uf != TODOS:
            fig.add_trace(go.Scatter(x=perfil_br.index, y=perfil_br.values, name="Brasil (seções com log)",
                                     mode="lines+markers", line=dict(color=COR_NORMAL, dash="dot")))
        fig.add_vline(x=16.5, line_dash="dash", annotation_text="17h")
        fig.update_layout(title="Distribuição dos votos ao longo do dia (horário de Brasília)",
                          xaxis=dict(tickmode="array", tickvals=list(perfil.index),
                                     ticktext=[f"{h}h" for h in perfil.index]),
                          yaxis_tickformat=".0%", height=420, legend=dict(orientation="h"))
        st.plotly_chart(fig, width="stretch")

        # média ± desvio por subunidade
        th = resumo_coluna(dh, "hora_media", filho)
        tard = dh.groupby(filho, observed=True)[["votos_apos_17", "votos_log"]].sum()
        tard["pct_apos_17"] = tard["votos_apos_17"] / tard["votos_log"]
        th = th.merge(tard["pct_apos_17"], left_on=filho, right_index=True, how="left")
        th[rotulo] = th[rotulo].astype(str)
        if len(th) <= 40:
            t = th.sort_values("media")
            fig = go.Figure(go.Scatter(
                x=t["media"], y=t[rotulo], mode="markers",
                error_x=dict(type="data", array=t["desvio_padrao"].fillna(0), color="#b8c0cc"),
                marker=dict(size=9, color="#33415c"),
                customdata=np.stack([t["secoes"], t["pct_apos_17"]], axis=1),
                hovertemplate="%{y}<br>hora média %{x:.2f}h<br>seções %{customdata[0]}<br>"
                              "votos após 17h %{customdata[1]:.2%}<extra></extra>"))
            fig.add_vline(x=dh["hora_media"].mean(), line_dash="dash", annotation_text="média do nível acima")
            fig.update_layout(title="Hora média do voto: média ± 1 desvio padrão entre as seções",
                              xaxis_title="hora (decimal, Brasília)", height=max(350, 22 * len(t) + 80),
                              margin=dict(l=10, r=10, t=50, b=10))
        else:
            fig = px.scatter(th, x="media", y="pct_apos_17", size="secoes", hover_name=rotulo,
                             color="desvio_padrao", color_continuous_scale="OrRd", size_max=35,
                             labels={"media": "hora média (decimal)", "pct_apos_17": "% dos votos após 17h",
                                     "desvio_padrao": "desvio (h)"},
                             title="Cada ponto é uma unidade: hora média × % dos votos após 17h")
            fig.update_layout(yaxis_tickformat=".1%", height=560)
        st.plotly_chart(fig, width="stretch")

        a, b = st.columns(2)
        m, sd = dh["hora_media"].mean(), dh["hora_media"].std()
        fig = histograma(dh["hora_media"], 80, "#33415c")
        for k, estilo in [(0, "solid"), (2, "dot"), (3, "dash")]:
            fig.add_vline(x=m + k * sd, line_dash=estilo, line_color=COR_ALTA if k else "black",
                          annotation_text="média" if k == 0 else f"+{k} dp")
        fig.update_layout(title="Hora média do voto, por seção", xaxis_title="hora (decimal)",
                          yaxis_title="seções", height=380)
        a.plotly_chart(fig, width="stretch")
        fig = histograma(dh.loc[dh["votos_apos_17"] > 0, "pct_apos_17"], 60, COR_ALTA, log_y=True)
        fig.update_layout(title="Seções com votos após 17h: % dos votos depois das 17h (escala log)",
                          xaxis_tickformat=".0%", xaxis_title="% dos votos após 17h", yaxis_title="seções",
                          height=380)
        b.plotly_chart(fig, width="stretch")

        st.markdown("**Seções com mais votos após 17h**")
        cols = [c for c in ["uf", "municipio", "zona", "secao", "votos_apos_17", "pct_apos_17", "sinais",
                            "ultimo_voto", "hora_media", "z_horario", "dif_local_min", "pct_sem_bio_apos_17",
                            "ociosa_antes_17_min", "taxa_abstencao", "votos_log", "nome_local"] if c in dh]
        idx_top = dh[["pct_apos_17", "votos_apos_17"]].sort_values(
            ["pct_apos_17", "votos_apos_17"], ascending=False).head(500).index
        top = dh.loc[idx_top]
        ev_h = st.dataframe(
            top[cols], hide_index=True, width="stretch", height=380, on_select="rerun",
            selection_mode="single-row", key="tab_hora",
            column_config={**{c: st.column_config.NumberColumn(format="percent")
                              for c in ["pct_apos_17", "pct_sem_bio_apos_17", "taxa_abstencao"]},
                           **{c: st.column_config.NumberColumn(format="%.2f")
                              for c in ["hora_media", "ultimo_voto", "z_horario"]},
                           **{c: st.column_config.NumberColumn(format="%.0f")
                              for c in ["dif_local_min", "ociosa_antes_17_min"]}})
        st.caption("Votar depois das 17h é permitido: quem está na fila às 17h vota. Em 2022 foram cerca "
                   "de 4 milhões de votos após as 17h no 1º turno. Por isso, olhe junto os sinais: "
                   "fila de verdade costuma afetar a escola inteira e vem precedida de uma última hora cheia.")
        if ev_h and ev_h.selection and ev_h.selection.rows:
            st.divider()
            detalhe_secao(top.iloc[ev_h.selection.rows[0]])

# ---------------------------------------------------------------- sem digital
with aba_dig:
    dd = com_log(df) if "pct_sem_digital" in df else df.iloc[0:0]
    if dd.empty:
        st.info(SEM_LOGS if not tem_logs else
                "Os logs foram processados por uma versão antiga. Rode `python baixar_logs.py --refazer`.")
    else:
        ind = st.radio("Indicador", ["Sem digital (total)", "Liberação manual (só quem tem digital)"],
                       horizontal=True,
                       help="Sem digital = eleitor sem digital cadastrada + eleitor liberado pelo mesário. "
                            "Liberação manual = eleitor TEM digital cadastrada, ela não foi reconhecida e o "
                            "mesário liberou com a digital dele.")
        total_ind = ind.startswith("Sem")
        col_p, col_z, col_esp = (("pct_sem_digital", "z_sem_digital", "sem_digital_esperado") if total_ind
                                 else ("pct_manual_cadastrados", "z_manual", "manual_esperado"))

        # perfil hora a hora
        tot, sd, man = (votos_por_hora(dd, p) for p in "hsm")
        horas_ = [h for h in range(6, 24) if tot[h] >= max(30, 0.001 * tot.sum())]
        fig = go.Figure()
        fig.add_trace(go.Bar(x=[f"{h}h" for h in horas_], y=[(sd[h] - man[h]) / tot[h] for h in horas_],
                             name="sem cadastro de digital", marker_color="#e0a33a",
                             customdata=[int(tot[h]) for h in horas_],
                             hovertemplate="%{x}: %{y:.1%} de %{customdata} votos<extra></extra>"))
        fig.add_trace(go.Bar(x=[f"{h}h" for h in horas_], y=[man[h] / tot[h] for h in horas_],
                             name="liberação manual pelo mesário", marker_color=COR_ALTA))
        fig.update_layout(barmode="stack", yaxis_tickformat=".0%", height=380, legend=dict(orientation="h"),
                          title="% dos eleitores de cada hora liberados SEM digital (horário de Brasília; "
                                "horas com menos de 30 votos omitidas)")
        st.plotly_chart(fig, width="stretch")

        # por subunidade
        agg = dd.groupby(filho, observed=True)[["votos_log", "votos_digital", "votos_sem_cadastro",
                                                "votos_manual"]].sum()
        agg["sem_digital_agregado"] = 1 - agg["votos_digital"] / agg["votos_log"]
        agg["manual_agregado"] = agg["votos_manual"] / (agg["votos_log"] - agg["votos_sem_cadastro"])
        td = resumo_coluna(dd, col_p, filho).merge(agg, left_on=filho, right_index=True, how="left")
        z3 = dd[dd[col_z] >= 3].groupby(filho, observed=True).size().rename("secoes_z3")
        td = td.merge(z3, left_on=filho, right_index=True, how="left").fillna({"secoes_z3": 0})
        td[rotulo] = td[rotulo].astype(str)
        if len(td) <= 40:
            t = td.sort_values("media")
            fig = go.Figure(go.Scatter(
                x=t["media"], y=t[rotulo], mode="markers",
                error_x=dict(type="data", array=t["desvio_padrao"].fillna(0), color="#b8c0cc"),
                marker=dict(size=9, color="#33415c"),
                customdata=np.stack([t["secoes"], t["secoes_z3"]], axis=1),
                hovertemplate="%{y}<br>média %{x:.1%}<br>seções %{customdata[0]}<br>"
                              "seções com z ≥ 3: %{customdata[1]}<extra></extra>"))
            fig.add_vline(x=dd[col_p].mean(), line_dash="dash", annotation_text="média do nível acima")
            fig.update_layout(title=f"{ind}: média ± 1 desvio padrão entre as seções",
                              xaxis_tickformat=".0%", height=max(350, 22 * len(t) + 80),
                              margin=dict(l=10, r=10, t=50, b=10))
        else:
            fig = px.scatter(td, x="sem_digital_agregado", y="manual_agregado", size="votos_log",
                             color="secoes_z3", hover_name=rotulo, color_continuous_scale="OrRd", size_max=35,
                             labels={"sem_digital_agregado": "% sem digital (total)",
                                     "manual_agregado": "% liberação manual (de quem tem digital)",
                                     "secoes_z3": "seções z≥3"},
                             title="Cada ponto é uma unidade: sem digital × liberação manual")
            fig.update_layout(xaxis_tickformat=".0%", yaxis_tickformat=".0%", height=560)
        st.plotly_chart(fig, width="stretch")

        # funil: proporção × número de votos
        pts = filtrar(dd, dd[col_z].notna(), ["municipio", "zona", "secao", col_p, col_z, col_esp,
                                              "votos_log", "votos_sem_cadastro"])
        den = pts["votos_log"] if total_ind else pts["votos_log"] - pts["votos_sem_cadastro"]
        flag = pts[col_z] >= limite
        keep = amostrar_fundo(pts[[]], flag).index
        pts, den, flag = pts.loc[keep], den.loc[keep], flag.loc[keep]
        fig = go.Figure()
        for nome, m, cor, tam, op in [("demais", ~flag, COR_NORMAL, 4, .35),
                                      (f"z ≥ {limite} (acima do esperado no município)", flag, COR_ALTA, 8, .95)]:
            d = pts[m]
            fig.add_trace(go.Scattergl(
                x=den[m], y=d[col_p], mode="markers", name=nome, marker=dict(size=tam, color=cor, opacity=op),
                text=(d["municipio"].astype(str) + " · Z" + d["zona"].astype(str) + " · S" + d["secao"].astype(str)
                      + "<br>esperado " + (d[col_esp] * 100).round(1).astype(str) + "% · z "
                      + d[col_z].round(1).astype(str)),
                hovertemplate="%{text}<br>%{y:.1%} de %{x} eleitores<extra></extra>"))
        fig.update_layout(title=f"{ind} × tamanho da seção (seções pequenas variam mais por acaso)",
                          xaxis_title="eleitores (votos no log)" if total_ind else "eleitores com digital cadastrada",
                          yaxis_title=ind, yaxis_tickformat=".0%", height=520, legend=dict(orientation="h"))
        st.plotly_chart(fig, width="stretch")

        sel = dd[dd[col_z] >= limite].sort_values(col_z, ascending=False)
        st.write(f"**{len(sel):,}** seções com {ind.lower()} {limite}+ desvios acima do esperado para o município. "
                 "Selecione uma linha para ver o detalhe.")
        cols = [c for c in ["uf", "municipio", "zona", "secao", col_z, col_p, col_esp, "pct_sem_cadastro",
                            "votos_manual", "maior_seq_manual", "dif_local_sem_digital_pp", "z_sem_digital",
                            "z_manual", "taxa_abstencao", "z_ajustado", "pct_apos_17", "sinais", "votos_log",
                            "nome_local"] if c in sel]
        cols = list(dict.fromkeys(cols))
        ev_d = st.dataframe(
            sel[cols], hide_index=True, width="stretch", height=400, on_select="rerun",
            selection_mode="single-row", key="tab_dig",
            column_config={**{c: st.column_config.NumberColumn(format="percent")
                              for c in ["pct_sem_digital", "pct_manual_cadastrados", "sem_digital_esperado",
                                        "manual_esperado", "pct_sem_cadastro", "taxa_abstencao", "pct_apos_17"]},
                           **{c: st.column_config.NumberColumn(format="%.2f")
                              for c in ["z_sem_digital", "z_manual", "z_ajustado"]},
                           "dif_local_sem_digital_pp": st.column_config.NumberColumn(format="%+.0f p.p.")})
        st.download_button("⬇️ Baixar lista (CSV)", sel[cols].to_csv(index=False, sep=";", decimal=",")
                           .encode("utf-8-sig"), "secoes_sem_digital.csv", "text/csv", key="dl_dig")
        st.caption("Liberar sem digital é previsto em lei e comum (~1 em cada 5 eleitores em 2022): "
                   "eleitor sem cadastro biométrico, idosos e trabalhadores braçais com digitais gastas, "
                   "leitor com defeito ou sujo. Por isso o z compara cada seção com o próprio município. "
                   "Sinais mais fortes: muitas LIBERAÇÕES MANUAIS (eleitor tinha digital), em SEQUÊNCIA, "
                   "numa seção que destoa das outras da mesma escola.")
        if ev_d and ev_d.selection and ev_d.selection.rows:
            st.divider()
            detalhe_secao(sel.iloc[ev_d.selection.rows[0]])

# ---------------------------------------------------------------- cruzamento
with aba_cruz:
    mask_c = (df["tem_log"] & df["score_cruzado"].notna()) if tem_logs else pd.Series(False, index=df.index)
    dc = filtrar(df, mask_c, ["municipio", "zona", "secao", "score_cruzado", "taxa_abstencao", "hora_media",
                              "pct_apos_17", "pct_sem_digital", "sinais"]
                 + [c for crit in CRITERIOS.values() for c in crit[:2]])
    if dc.empty:
        st.info(SEM_LOGS)
    else:
        st.markdown(f"**Critérios (barra lateral):** {NOME_CRUZ} — todos ≥ {limite_cruz} desvios.")
        cx = criterios[0]
        cy = criterios[1] if len(criterios) > 1 else ("Votação tardia" if cx != "Votação tardia" else "Abstenção baixa")
        eixos = st.radio("Eixos", ["Padronizados (z, comparando com o próprio município)", "Valores brutos"],
                         horizontal=True)
        padr = eixos.startswith("Padr")
        xcol = CRITERIOS[cx][0] if padr else CRITERIOS[cx][1]
        ycol = CRITERIOS[cy][0] if padr else CRITERIOS[cy][1]
        if xcol not in dc or ycol not in dc:
            st.warning("Indicador indisponível nestes dados. Rode `python baixar_logs.py --refazer`.")
            st.stop()
        destaque = dc["score_cruzado"] >= limite_cruz
        pontos = dc
        pontos = amostrar_fundo(dc, destaque)
        hover = (pontos["municipio"].astype(str) + " · Z" + pontos["zona"].astype(str) + " · S"
                 + pontos["secao"].astype(str) + "<br>abstenção " + (pontos["taxa_abstencao"] * 100).round(1).astype(str)
                 + "% · hora média " + pontos["hora_media"].map(hora) + " · após 17h "
                 + (pontos["pct_apos_17"] * 100).round(1).astype(str) + "%")
        if "pct_sem_digital" in pontos:
            hover = hover + " · sem digital " + (pontos["pct_sem_digital"] * 100).round(1).astype(str) + "%"
        hover = hover + "<br>" + pontos["sinais"].fillna("")
        fig = go.Figure()
        for nome, mask, cor, tam, op in [("demais seções", pontos["score_cruzado"] < limite_cruz, COR_NORMAL, 4, .35),
                                         (NOME_CRUZ, pontos["score_cruzado"] >= limite_cruz, COR_ALTA, 9, .95)]:
            d = pontos[mask]
            fig.add_trace(go.Scattergl(
                x=d[xcol].clip(-12, 15) if padr else d[xcol], y=d[ycol].clip(-12, 15) if padr else d[ycol],
                mode="markers", name=nome, marker=dict(size=tam, color=cor, opacity=op),
                text=hover[mask], hovertemplate="%{text}<extra></extra>"))
        if padr:
            fig.add_shape(type="rect", x0=limite_cruz, x1=15, y0=limite_cruz, y1=15,
                          fillcolor=COR_ALTA, opacity=0.07, line_width=0)
            for v in (-limite_cruz, limite_cruz):
                fig.add_vline(x=v, line_dash="dot", line_color="#888")
                fig.add_hline(y=v, line_dash="dot", line_color="#888")
            fig.update_layout(xaxis_title=EIXO_Z[cx], yaxis_title=EIXO_Z[cy])
        else:
            fig.update_layout(xaxis_title=CRITERIOS[cx][2], yaxis_title=CRITERIOS[cy][2],
                              xaxis_tickformat=".0%", yaxis_tickformat=".0%")
        extra = f" (os demais critérios — {', '.join(criterios[2:]).lower()} — entram no destaque)" \
            if len(criterios) > 2 else ""
        fig.update_layout(title=f"Cada ponto é uma seção: {cx.lower()} × {cy.lower()}{extra}", height=620,
                          legend=dict(orientation="h"))
        st.plotly_chart(fig, width="stretch")

        sel = df[mask_c & (df["score_cruzado"] >= limite_cruz)].sort_values(["score_cruzado", "n_sinais"],
                                                                               ascending=False)
        st.write(f"**{len(sel):,}** seções com {NOME_CRUZ} (todos ≥ {limite_cruz}), de {len(dc):,} com log. "
                 "Ordenadas pelo score; a coluna *sinais* resume o que o log mostra.")
        cols = [c for c in ["uf", "municipio", "zona", "secao", "score_cruzado", "n_sinais", "sinais",
                            "taxa_abstencao", "z_ajustado", "hora_media", "z_horario", "pct_apos_17",
                            "pct_sem_digital", "z_sem_digital", "pct_manual_cadastrados", "z_manual",
                            "maior_seq_manual", "ociosa_antes_17_min", "dif_local_min", "aptos", "nome_local"]
                if c in sel]
        ev_c = st.dataframe(
            sel[cols], hide_index=True, width="stretch", height=420, on_select="rerun",
            selection_mode="single-row", key="tab_cruz",
            column_config={**{c: st.column_config.NumberColumn(format="percent")
                              for c in ["taxa_abstencao", "pct_apos_17", "pct_sem_digital", "pct_manual_cadastrados"]},
                           **{c: st.column_config.NumberColumn(format="%.2f")
                              for c in ["z_ajustado", "hora_media", "z_horario", "score_cruzado", "z_sem_digital",
                                        "z_manual"]},
                           **{c: st.column_config.NumberColumn(format="%.0f")
                              for c in ["dif_local_min", "ociosa_antes_17_min"]}})
        st.download_button("⬇️ Baixar lista (CSV)", sel[cols].to_csv(index=False, sep=";", decimal=",")
                           .encode("utf-8-sig"), "cruzamento.csv", "text/csv", key="dl_cruz")
        st.caption("Indicadores andam juntos por motivos comuns: mais eleitores → mais fila → votação tardia; "
                   "região sem cadastro biométrico → mais eleitores sem digital. O que diferencia é o contexto: "
                   "compare com as outras seções da mesma escola (detalhe da seção) e veja os sinais do log.")
        if ev_c and ev_c.selection and ev_c.selection.rows:
            st.divider()
            detalhe_secao(sel.iloc[ev_c.selection.rows[0]])


# ---------------------------------------------------------------- 1º × 2º turno
with aba_turnos:
    ano_sel = arquivo.stem.split("_")[1]
    if arquivos_turnos(ano_sel) is None:
        st.info("Para comparar os turnos faltam arquivos em `dados/`. Rode, nesta ordem:\n\n"
                "`python baixar_dados.py --turno 1`, `python baixar_dados.py --turno 2` e "
                "`python baixar_votos.py` (votos de cada candidato por seção, dos boletins de urna).")
    else:
        cands = candidatos_turnos(ano_sel)
        cand = st.radio("Candidato", list(cands), horizontal=True, key="cand_turnos",
                        format_func=lambda n: NOMES_CURTOS.get(n, cands[n].title()))
        arqs_t = arquivos_turnos(ano_sel)
        cmp_base = carregar_comparacao(ano_sel, cand, tuple((p.name, p.stat().st_mtime) for p in arqs_t.values()),
                                       incluir_zz)
        m = pd.Series(True, index=cmp_base.index)
        if uf != TODOS:
            m &= cmp_base["uf"] == uf
        if mun != TODOS:
            m &= cmp_base["cd_municipio"] == mun
        if zona != TODOS:
            m &= cmp_base["zona"] == zona
        dt = cmp_base if bool(m.all()) else cmp_base[m]

        v1, v2 = int(dt["votos1"].sum()), int(dt["votos2"].sum())
        q1, q2 = dt["validos1"].sum(), dt["validos2"].sum()
        c = st.columns(5)
        c[0].metric("Seções comparadas", f"{len(dt):,}".replace(",", "."))
        c[1].metric("1º turno", pct(v1 / q1, 2), help=f"{v1:,} votos, % dos votos válidos".replace(",", "."))
        c[2].metric("2º turno", pct(v2 / q2, 2), help=f"{v2:,} votos, % dos votos válidos".replace(",", "."))
        c[3].metric("Variação", f"{(v2 / q2 - v1 / q1) * 100:+.2f} p.p.")
        c[4].metric("Votos ganhos", f"{v2 - v1:+,}".replace(",", "."),
                    help="Votos do 2º turno menos votos do 1º, somando as seções (inclui efeito do comparecimento)")

        with st.expander("ℹ️ Como ler esta comparação"):
            st.markdown(
                "- **% válidos**: votos do candidato ÷ votos válidos da seção (sem branco e nulo). No 1º turno "
                "havia vários candidatos; no 2º, dois. Por isso quase todo mundo sobe e o valor bruto "
                "diz pouco.\n"
                "- **Variação do município**: quanto o município (sem a própria seção; a UF, se tiver menos de "
                "5 seções) subiu ou desceu. É a \"onda\" local.\n"
                "- **Desvio (p.p.)**: o que a seção teve no 2º turno menos o que se esperaria se ela seguisse a onda "
                "do município. Positivo = foi melhor que o município; negativo = pior.\n"
                "- **Votos × esperado**: o mesmo desvio, em votos. Mostra onde o candidato ganhou ou perdeu "
                "mais votos além do esperado.\n"
                "- **z do desvio**: o desvio em relação ao acaso e à variação natural entre seções da UF. "
                "Seções pequenas oscilam muito: olhe o z, não só os pontos percentuais.\n"
                "- Mudança grande **não é prova de irregularidade**: troca de local de votação, seção "
                "nova ou desmembrada, perfil do eleitorado, voto de candidatos eliminados e mobilização local "
                "explicam a maioria.")

        nome_c = NOMES_CURTOS.get(cand, cands[cand].title().split()[0])
        MEDIDAS = {"z do desvio": ("z_desvio", 4.0, 0.5), "Votos × esperado": ("votos_vs_esperado", 20.0, 10.0),
                   "Variação em votos": ("delta_votos", 50.0, 10.0)}
        k = st.columns(5)
        medida_t = k[0].radio("Filtrar e ordenar por", list(MEDIDAS), key="medida_turnos",
                              help="z = desvio contra o município, corrigido pelo acaso. Votos × esperado = o "
                                   "mesmo desvio em votos. Variação em votos = votos do 2º turno menos os do 1º, "
                                   "sem comparar com o município.")
        col_t, lim_pad, passo = MEDIDAS[medida_t]
        modo = k[1].radio("Onde o candidato escolhido…", ["foi melhor que o município (ganhou mais)",
                                                           "foi pior que o município (perdeu mais)",
                                                           "nos dois sentidos"], index=2, key="modo_turnos",
                          help="Com dois candidatos no 2º turno, onde um vai melhor o outro vai pior: "
                               "'foi pior' para um é, na prática, 'foi melhor' para o outro.")
        lim_t = k[2].number_input(f"Mínimo (em valor absoluto) de: {medida_t}", 0.0, 100000.0, lim_pad, passo,
                                  key=f"lim_turnos_{col_t}")
        min_val = k[3].number_input("Mín. votos válidos nos dois turnos", 0, 500, 50, 10, key="minval_turnos")
        min_vot = k[4].number_input("Mín. |votos × esperado|", 0, 1000, 20, 5, key="minvot_turnos",
                                    help="Além do corte ao lado: ignora desvios que, em votos, são pequenos "
                                         "(seção pequena com z alto por poucos votos).")

        ok = (dt["validos1"] >= min_val) & (dt["validos2"] >= min_val)
        alvo = ok & (dt[col_t].abs() >= lim_t) & (dt["votos_vs_esperado"].abs() >= min_vot)
        if "pior" in modo:
            alvo &= dt[col_t] < 0
        elif "melhor" in modo:
            alvo &= dt[col_t] > 0

        # --- por unidade (UF, município, zona ou local)
        g = dt.groupby(filho, observed=True)
        unid = g.agg(secoes=("votos1", "size"), votos1=("votos1", "sum"), votos2=("votos2", "sum"),
                     validos1=("validos1", "sum"), validos2=("validos2", "sum"),
                     votos_vs_esperado=("votos_vs_esperado", "sum")).reset_index()
        unid["pct1"], unid["pct2"] = unid["votos1"] / unid["validos1"], unid["votos2"] / unid["validos2"]
        unid["variacao_pp"] = (unid["pct2"] - unid["pct1"]) * 100
        unid["delta_votos"] = unid["votos2"] - unid["votos1"]
        sin = alvo.groupby([dt[f] for f in filho], observed=True).sum().rename("sinalizadas").reset_index()
        unid = unid.merge(sin, on=filho, how="left")
        unid[rotulo] = unid[rotulo].astype(str)
        st.subheader(f"Por {rotulo.replace('municipio', 'município')}")
        st.dataframe(unid.drop(columns=[c for c in ["cd_municipio"] if c in unid and rotulo != "cd_municipio"])
                     .sort_values("variacao_pp"), hide_index=True, width="stretch", height=300,
                     column_config={"pct1": st.column_config.NumberColumn("% 1", format="percent"),
                                    "pct2": st.column_config.NumberColumn("% 2", format="percent"),
                                    "variacao_pp": st.column_config.NumberColumn("variação (p.p.)", format="%+.2f"),
                                    "votos_vs_esperado": st.column_config.NumberColumn("votos × esperado", format="%+.0f"),
                                    "delta_votos": st.column_config.NumberColumn("votos ganhos", format="%+d")})

        # --- gráficos
        c1, c2 = st.columns(2)
        with c1:
            fig = histograma(dt.loc[ok, "desvio_pp"] * 100, 80, "#33415c")
            fig.add_vline(x=0, line_color="black")
            fig.update_layout(title="Desvio de cada seção em relação ao município (p.p.)",
                              xaxis_title="desvio (p.p.): negativo = pior que o município",
                              yaxis_title="seções", height=420)
            st.plotly_chart(fig, width="stretch")
        with c2:
            pontos = dt.loc[ok, ["esperado_pp", "pct2", "municipio", "zona", "secao", "z_desvio"]]
            alv = alvo.loc[pontos.index]
            pontos = amostrar_fundo(pontos, alv)
            fig = go.Figure()
            for nome, msk, cor, tam, op in [("demais", ~pontos.index.isin(alvo[alvo].index), COR_NORMAL, 4, .35),
                                            ("destacadas", pontos.index.isin(alvo[alvo].index), COR_ALTA, 8, .9)]:
                p_ = pontos[msk]
                fig.add_trace(go.Scattergl(
                    x=p_["esperado_pp"], y=p_["pct2"], mode="markers", name=nome,
                    marker=dict(size=tam, color=cor, opacity=op),
                    text=p_["municipio"].astype(str) + " · Z" + p_["zona"].astype(str) + " · S" + p_["secao"].astype(str)
                         + "<br>z " + p_["z_desvio"].round(1).astype(str),
                    hovertemplate="%{text}<br>esperado %{x:.1%} · teve %{y:.1%}<extra></extra>"))
            fig.add_shape(type="line", x0=0, y0=0, x1=1, y1=1, line=dict(color="black", dash="dot"))
            fig.update_layout(title="No 2º turno: esperado × realizado (% válidos)", xaxis_tickformat=".0%",
                              yaxis_tickformat=".0%", xaxis_title="esperado (seguindo o município)",
                              yaxis_title="realizado", height=420,
                              legend=dict(orientation="h", y=1.12, x=0))
            st.plotly_chart(fig, width="stretch")

        # --- lista de seções
        sel = dt[alvo]
        if "pior" in modo:
            sel = sel.sort_values(col_t)
        elif "melhor" in modo:
            sel = sel.sort_values(col_t, ascending=False)
        else:
            sel = sel.reindex(sel[col_t].abs().sort_values(ascending=False).index)
        st.subheader(f"{len(sel):,} seções".replace(",", ".") + f" · {nome_c} {modo.split(' (')[0]} · {medida_t.lower()} ≥ {lim_t:g}")
        cols = [c for c in ["uf", "municipio", "zona", "secao", "z_desvio", "votos_vs_esperado", "delta_votos",
                            "pct1", "pct2", "esperado_pp", "desvio_pp", "votos1", "votos2", "validos1", "validos2",
                            "taxa_abst1", "taxa_abst2", "var_abst_pp", "aptos", "nome_local"] if c in sel]
        st.dataframe(sel[cols], hide_index=True, width="stretch", height=420,
                     column_config={**{c: st.column_config.NumberColumn(format="percent")
                                       for c in ["esperado_pp", "desvio_pp", "taxa_abst1", "taxa_abst2",
                                                 "var_abst_pp"]},
                                    "pct1": st.column_config.NumberColumn("% 1", format="percent"),
                                    "pct2": st.column_config.NumberColumn("% 2", format="percent"),
                                    "z_desvio": st.column_config.NumberColumn("z do desvio", format="%.2f"),
                                    "votos_vs_esperado": st.column_config.NumberColumn("votos × esperado", format="%+.0f"),
                                    "delta_votos": st.column_config.NumberColumn("votos ganhos", format="%+d")})
        st.download_button("⬇️ Baixar lista (CSV)", sel[cols].rename(columns={"pct1": "% 1", "pct2": "% 2"})
                           .to_csv(index=False, sep=";", decimal=",").encode("utf-8-sig"), f"turnos_{cand}.csv", "text/csv", key="dl_turnos")
        st.caption("Compare com as outras seções da mesma escola e veja se houve mudança de local ou "
                   "desmembramento de seções entre os turnos. Um desvio isolado em seção pequena é comum.")


# ---------------------------------------------------------------- fluxo de votos entre turnos
def _rotulo_origem(k: str, cands: dict[int, str]) -> str:
    fixos = {"demais": "Demais candidatos", "brancos_nulos": "Brancos e nulos", "abstencao": "Abstenção"}
    if k in fixos:
        return fixos[k]
    n = int(k[1:])
    return ("Eleitores de " if k[0] == "f" else "") + NOMES_CURTOS.get(n, cands.get(n, k).title().split()[0])


def _mi(x: float) -> str:
    return f"{x / 1e6:,.2f} mi".replace(",", "X").replace(".", ",").replace("X", ".") if abs(x) >= 1e5 \
        else f"{x / 1e3:,.0f} mil".replace(",", ".")


with aba_fluxo:
    ano_f = arquivo.stem.split("_")[1]
    if arquivos_turnos(ano_f) is None:
        st.info("Para estimar o fluxo de votos faltam arquivos em `dados/`. Rode `python baixar_dados.py --turno 1`, "
                "`python baixar_dados.py --turno 2` e `python baixar_votos.py`.")
    else:
        cands_f = candidatos_turnos(ano_f)
        prep = carregar_fluxo(ano_f, tuple((q.name, q.stat().st_mtime) for q in arquivos_turnos(ano_f).values()),
                              incluir_zz)
        nivel_f = "Brasil" if uf == TODOS else uf
        res = estimar_fluxos(prep, None if uf == TODOS else [uf], n_boot=100)
        F, lo, hi = res["F"], res["lo"], res["hi"]
        orig, dest = list(F.index), list(F.columns)
        nome_o = {k: _rotulo_origem(k, cands_f) for k in orig}
        nome_d = {k: (_rotulo_origem(k, cands_f).replace("Eleitores de ", "") if k.startswith("f")
                      else _rotulo_origem(k, cands_f)) for k in dest}
        fin = [k for k in dest if k.startswith("f")]
        st.subheader(f"Para onde foram os eleitores do 1º turno — {nivel_f}")
        if mun != TODOS:
            st.info("A estimativa precisa de muitas seções; com um município só ela fica instável. "
                    f"Mostrando {nivel_f}.")
        st.caption("Estimativa a partir dos boletins de urna de cada seção nos dois turnos. "
                   "**Não é contagem** (o voto é secreto): é o fluxo que melhor explica as diferenças entre seções.")

        # --- quanto cada finalista ganhou e de onde veio
        total1 = F.sum(axis=1)
        cols = st.columns(len(fin))
        for c, k in zip(cols, fin):
            v1_, v2_ = float(total1[k]), float(F[k].sum())
            novos = F[k].drop(index=k)
            c.metric(f"{nome_d[k]}: votos ganhos", ("+" if v2_ >= v1_ else "") + _mi(v2_ - v1_),
                     help=f"{_mi(v1_)} no 1º turno → {_mi(v2_)} no 2º (zona exterior fora)")
            c.caption("Vieram, na estimativa, de: " + " · ".join(
                f"{nome_o[o]} {_mi(float(x))}" for o, x in novos.sort_values(ascending=False).items() if x >= 5e4))

        # --- Sankey
        so_mov = st.checkbox("Mostrar só quem mudou de escolha (esconde quem repetiu o voto)", value=True,
                             key="fluxo_so_mov")
        pares = [(o, d_) for o in orig for d_ in dest if F.loc[o, d_] > 0.002 * F.to_numpy().sum()
                 and not (so_mov and o == d_)]
        cor_dest = {"f13": "214,69,61", "f22": "47,111,181", "brancos_nulos": "154,164,177", "abstencao": "120,120,120"}
        nos_o = [f"1º · {nome_o[o]}" for o in orig]
        nos_d = [f"2º · {nome_d[d_]}" for d_ in dest]
        fig = go.Figure(go.Sankey(
            arrangement="snap",
            node=dict(label=nos_o + nos_d, pad=14, thickness=16,
                      color=["#9aa4b1"] * len(orig) + ["#33415c"] * len(dest)),
            link=dict(source=[orig.index(o) for o, _ in pares],
                      target=[len(orig) + dest.index(d_) for _, d_ in pares],
                      value=[float(F.loc[o, d_]) for o, d_ in pares],
                      color=[f"rgba({cor_dest.get(d_, '154,164,177')},0.45)" for _, d_ in pares],
                      customdata=[_mi(float(F.loc[o, d_])) for o, d_ in pares],
                      hovertemplate="%{source.label} → %{target.label}<br>%{customdata}<extra></extra>")))
        fig.update_traces(textfont=dict(color="#1f2937", size=13), selector=dict(type="sankey"))
        fig.update_layout(height=520, margin=dict(l=10, r=10, t=30, b=10),
                          title="Cada faixa: eleitores de um grupo no 1º turno e o que fizeram no 2º")
        st.plotly_chart(fig, width="stretch")

        # --- de onde veio o voto de cada finalista (com intervalo)
        st.markdown("**De onde veio o voto de cada finalista no 2º turno** (estimativa, intervalo de 90%)")
        linhas = []
        for o in orig:
            lin = {"Grupo no 1º turno": nome_o[o]}
            for k in fin:
                x = float(F.loc[o, k])
                lin[f"{nome_d[k]}: votos"] = x
                lin[f"{nome_d[k]}: % do total"] = x / float(F[k].sum())
                lin[f"{nome_d[k]}: intervalo"] = f"{_mi(float(lo.loc[o, k]))} – {_mi(float(hi.loc[o, k]))}"
            linhas.append(lin)
        t_orig = pd.DataFrame(linhas)
        st.dataframe(t_orig, hide_index=True, width="stretch",
                     column_config={**{c: st.column_config.NumberColumn(format="%d") for c in t_orig if c.endswith(": votos")},
                                    **{c: st.column_config.NumberColumn(format="percent") for c in t_orig
                                       if c.endswith("% do total")}})

        # --- para onde foi cada grupo
        st.markdown("**Para onde foi cada grupo do 1º turno** (% de cada linha)")
        pct_ = F.div(F.sum(axis=1), axis=0)
        t_dest = pct_.rename(index=nome_o, columns=nome_d).reset_index(names="Grupo no 1º turno")
        t_dest.insert(1, "eleitores", F.sum(axis=1).to_numpy())
        st.dataframe(t_dest, hide_index=True, width="stretch",
                     column_config={"eleitores": st.column_config.NumberColumn("eleitores (1º turno)", format="%d"),
                                    **{c: st.column_config.NumberColumn(format="percent") for c in nome_d.values()}})

        # --- comparar UFs
        with st.expander("Comparar todas as UFs"):
            alvo_f = fin[0]
            nomes_uf = sorted(set(prep["uf"]))
            comp = []
            for u in nomes_uf:
                Fu = estimar_fluxos(prep, [u])["F"]
                pu = Fu.div(Fu.sum(axis=1), axis=0)
                lin = {"UF": u, f"{nome_d[alvo_f]}: votos ganhos": float(Fu[alvo_f].sum() - Fu.sum(axis=1)[alvo_f])}
                for o in orig:
                    if o != alvo_f:
                        lin[f"{nome_o[o]} → {nome_d[alvo_f]}"] = float(pu.loc[o, alvo_f])
                comp.append(lin)
            t_uf = pd.DataFrame(comp).sort_values(f"{nome_d[alvo_f]}: votos ganhos", ascending=False)
            st.caption(f"% dos eleitores de cada grupo do 1º turno que foram para {nome_d[alvo_f]}, por UF. "
                       "UFs pequenas variam mais por acaso.")
            st.dataframe(t_uf, hide_index=True, width="stretch",
                         column_config={**{c: st.column_config.NumberColumn(format="percent") for c in t_uf
                                           if "→" in c},
                                        f"{nome_d[alvo_f]}: votos ganhos": st.column_config.NumberColumn(format="%+d")})

        with st.expander("ℹ️ Como ler e o que esta estimativa NÃO mostra"):
            st.markdown(
                "- **Como é feito**: em cada seção, olha-se quantos eleitores cada grupo tinha no 1º turno "
                "(votou em cada candidato, branco/nulo, absteve-se) e quantos foram para cada destino no 2º. "
                "Uma regressão encontra os percentuais de fluxo que melhor explicam as diferenças entre as seções, "
                "sem permitir fluxo negativo. Depois os totais são ajustados para fechar exatamente.\n"
                "- **Troca de lado invisível**: se mil eleitores foram do Flávio para o Lula e mil do Lula para o "
                "Flávio, os dados agregados não mostram. O que aparece é só o fluxo líquido.\n"
                "- **Fluxos fracos**: os grupos andam juntos no mapa (regiões onde há mais brancos e nulos tendem a "
                "ter mais abstenção), então o método separa mal alguns deles. O intervalo cobre só o acaso das "
                "amostras de municípios, **não** erros do método.\n"
                "- **Falácia ecológica**: a estimativa descreve grupos de seções, não pessoas. É um bom guia de "
                "ordem de grandeza, nunca prova de como alguém votou.\n"
                "- **Seleção no mapa**: o filtro de UF vale; município e zona têm poucas seções para estimar.")


# ---------------------------------------------------------------- de onde vêm os votos (versão simples)
def _grupo_simples(k: str, cands: dict[int, str]) -> str:
    if k == "demais":
        return "Votaram em outros candidatos"
    if k == "brancos_nulos":
        return "Votaram em branco ou nulo"
    if k == "abstencao":
        return "Não votaram no 1º turno"
    n = int(k[1:])
    return "Votaram no " + NOMES_CURTOS.get(n, cands.get(n, k).title().split()[0]) + " no 1º turno"


def _qtd(x: float) -> str:
    """Quantidade de votos em linguagem comum: '10,87 milhões', '870 mil', '4 mil'."""
    return f"{_pt(x / 1e6, 2)} milhões" if abs(x) >= 1e6 else f"{_pt(round(x / 1e3))} mil"


def _sp(x: float, casas: int = 1) -> str:
    """Número com sinal explícito: +4,9 / −0,3."""
    return ("+" if x >= 0 else "−") + _pt(abs(x), casas)


def _frase(s: str) -> str:
    return s[0].lower() + s[1:]


def _pt(x: float, casas: int = 0) -> str:
    return f"{x:,.{casas}f}".replace(",", "X").replace(".", ",").replace("X", ".")


with aba_origem:
    ano_o = arquivo.stem.split("_")[1]
    if arquivos_turnos(ano_o) is None:
        st.info("Para ver esta seção faltam arquivos em `dados/`. Rode `python baixar_dados.py --turno 1`, "
                "`python baixar_dados.py --turno 2` e `python baixar_votos.py`.")
    else:
        cands_o = candidatos_turnos(ano_o)
        prep_o = carregar_fluxo(ano_o, tuple((q.name, q.stat().st_mtime) for q in arquivos_turnos(ano_o).values()),
                                incluir_zz)
        c1_, c2_ = st.columns([2, 1])
        escolha = c1_.radio("Candidato", sorted(cands_o), horizontal=True, key="origem_cand",
                            format_func=lambda n: NOMES_CURTOS.get(n, cands_o[n].title().split()[0]))
        local = c2_.selectbox("Estado", ["Brasil"] + sorted(set(prep_o["uf"])), key="origem_uf")
        quem = NOMES_CURTOS.get(escolha, cands_o[escolha].title().split()[0])
        alvo_o = f"f{escolha}"
        res_o = estimar_fluxos(prep_o, None if local == "Brasil" else [local], n_boot=100)
        Fo, lo_o, hi_o = res_o["F"], res_o["lo"], res_o["hi"]
        col = Fo[alvo_o]
        total = float(col.sum())
        proprios = float(col[alvo_o])
        novos = total - proprios
        eleit_1t = float(Fo.sum(axis=1)[alvo_o])

        st.subheader(f"De onde vêm os votos do {quem} no 2º turno — {local}")
        st.markdown(
            f"No 2º turno, o {quem} teve **{_qtd(total)} de votos** "
            f"{'no Brasil' if local == 'Brasil' else 'em ' + local}. "
            f"Cerca de **{_pt(proprios / total * 100)}%** deles ({_qtd(proprios)}) já tinham votado nele "
            f"no 1º turno. Os outros **{_qtd(novos)}** são votos novos.")
        novos_ord = col.drop(index=alvo_o).sort_values(ascending=False)
        novos_ord = novos_ord[novos_ord >= 0.01 * max(novos, 1)]
        if len(novos_ord):
            partes = [f"{_frase(_grupo_simples(o, cands_o))} ({_pt(float(v) / novos * 100)}% dos novos, {_qtd(float(v))})"
                      for o, v in novos_ord.head(3).items()]
            frase = "a maior parte veio dos eleitores que " + partes[0]
            if len(partes) > 1:
                frase += ", seguidos dos que " + partes[1]
            if len(partes) > 2:
                frase += " e dos que " + partes[2]
            st.markdown("Dos votos novos, " + frase + ".")
        fiel = float(Fo.loc[alvo_o, alvo_o]) / eleit_1t if eleit_1t else float("nan")
        st.caption(f"Fidelidade: de cada 100 eleitores do {quem} no 1º turno, cerca de {_pt(fiel * 100)} votaram nele "
                   "de novo.")

        # --- uma barra só com a composição dos votos
        cor_g = {alvo_o: "#b3342d", "c70": "#33415c", "c14": "#5b7db1", "c55": "#8fa8cf", "demais": "#c3cfe3",
                 "brancos_nulos": "#9aa4b1", "abstencao": "#e0a43b"}
        ordem_g = [alvo_o] + [o for o in novos_ord.index] + [o for o in col.index
                                                             if o != alvo_o and o not in novos_ord.index
                                                             and col[o] > 0]
        fig = go.Figure()
        for o in ordem_g:
            v = float(col[o])
            fig.add_trace(go.Bar(
                y=[""], x=[v / total * 100], orientation="h", name=_grupo_simples(o, cands_o) if o != alvo_o
                else f"Já votaram no {quem} no 1º turno",
                marker_color=cor_g.get(o, "#2f6fb5"),
                text=f"{v / total * 100:.0f}%" if v / total >= 0.04 else "", textposition="inside",
                insidetextfont=dict(color="white", size=14),
                hovertemplate=f"%{{x:.1f}}% · {_qtd(v)}<extra>%{{fullData.name}}</extra>"))
        fig.update_layout(barmode="stack", height=210, xaxis=dict(range=[0, 100], ticksuffix="%",
                          title="% dos votos do 2º turno"), margin=dict(l=10, r=10, t=10, b=10),
                          legend=dict(orientation="h", y=-0.55, x=0))
        st.plotly_chart(fig, width="stretch")

        # --- votos novos, um a um
        st.markdown(f"**Os {_qtd(novos)} de votos novos do {quem}, por origem**")
        if len(novos_ord):
            n_ = novos_ord.sort_values()
            fig = go.Figure(go.Bar(
                y=[_grupo_simples(o, cands_o) for o in n_.index], x=n_.to_numpy() / 1e6, orientation="h",
                marker_color=[cor_g.get(o, "#2f6fb5") for o in n_.index],
                text=[_qtd(float(v)) for v in n_], textposition="outside",
                hovertemplate="%{y}: %{x:.2f} mi<extra></extra>"))
            fig.update_layout(height=60 + 46 * len(n_), margin=dict(l=10, r=40, t=10, b=10),
                              xaxis=dict(visible=False, range=[0, float(n_.max()) / 1e6 * 1.3]))
            st.plotly_chart(fig, width="stretch")

        # --- tabela simples
        st.markdown("**Por grupo de eleitores**")
        linhas = []
        for o in col.index:
            if o == alvo_o or col[o] <= 0:
                continue
            base_g = float(Fo.sum(axis=1)[o])
            linhas.append({"Quem eram no 1º turno": _grupo_simples(o, cands_o),
                           "Eleitores nesse grupo": base_g,
                           f"Votaram no {quem} (estimativa)": float(col[o]),
                           f"De cada 100, quantos votaram no {quem}": float(col[o]) / base_g * 100 if base_g else np.nan,
                           "Faixa provável (votos)": f"{_mi(float(lo_o.loc[o, alvo_o]))} a {_mi(float(hi_o.loc[o, alvo_o]))}"})
        st.dataframe(pd.DataFrame(linhas), hide_index=True, width="stretch",
                     column_config={"Eleitores nesse grupo": st.column_config.NumberColumn(format="%d"),
                                    f"Votaram no {quem} (estimativa)": st.column_config.NumberColumn(format="%d"),
                                    f"De cada 100, quantos votaram no {quem}": st.column_config.NumberColumn(format="%.0f")})

        with st.expander("ℹ️ Como esta estimativa é feita e o que ela não mostra"):
            st.markdown(
                "- O voto é secreto: **ninguém sabe como cada pessoa votou**. Esta é uma estimativa feita comparando, "
                "seção por seção, o resultado do 1º e do 2º turno.\n"
                "- Funciona assim: se numa seção havia muitos eleitores de um candidato eliminado e o {q} cresceu "
                "bastante nessa seção, isso sugere que parte desses eleitores foi para ele. Repetindo isso em milhares "
                "de seções, dá para estimar proporções.\n"
                "- Os números são **ordens de grandeza**, não contagens. A \"faixa provável\" mostra a margem de "
                "erro por acaso, mas não cobre erros do método.\n"
                "- Algumas origens são difíceis de separar (por exemplo, quem votou em branco ou nulo e quem não foi "
                "votar costumam estar nos mesmos lugares). Por isso essas duas estimativas são as menos firmes.\n"
                "- Se muitos eleitores trocaram de lado em sentidos opostos ao mesmo tempo, isso não aparece: só o "
                "saldo.".replace("{q}", quem))


# ---------------------------------------------------------------- seções de risco (1º turno) × melhora no 2º
with aba_risco:
    ano_r = arquivo.stem.split("_")[1]
    if not arquivo_risco(ano_r).exists():
        st.info("Esta aba lê um arquivo pré-calculado que ainda não existe. Gere-o (precisa dos logs do 1º turno): "
                "`python baixar_logs.py --turno 1` e depois `python gerar_resultado_risco.py`.")
    else:
        st.subheader("Seções de risco do 1º turno × desempenho no 2º")
        st.caption("Os critérios de risco vêm dos **logs das urnas do 1º turno** (o TSE ainda não publicou os do 2º). "
                   "Aqui eles são cruzados com o desempenho do candidato no 2º turno em relação ao seu município. "
                   "Os dados desta aba são um resultado pré-calculado (exterior fora).")
        cand_r = st.session_state.get("risco_cand", candidatos_risco(ano_r)[0])
        pacote = carregar_risco(ano_r, cand_r, (arquivo_risco(ano_r).stat().st_mtime,))
        if pacote["n_ufs_log"] < 26:
            st.warning(f"O arquivo pré-calculado cobre {pacote['n_ufs_log']} de 26 UFs.")

        c1_, c2_ = st.columns([1, 1])
        c1_.radio("Candidato", candidatos_risco(ano_r), horizontal=True, key="risco_cand",
                  format_func=lambda n: NOMES_CURTOS.get(n, str(n)))
        ufs_r = sorted(pacote["mr"]["uf"].unique())
        local_r = c2_.selectbox("Estado", ["Brasil"] + ufs_r, key="risco_uf")
        quem_r = NOMES_CURTOS.get(cand_r, str(cand_r))

        with st.expander("Ajustar os critérios de risco (mesmos do painel original)"):
            k = st.columns(3)
            medida_r = k[0].selectbox("Medida da abstenção", ["z_ajustado", "z_binomial", "z_simples"],
                                      key="risco_medida", format_func={"z_ajustado": "z ajustado (recomendado)",
                                                                       "z_binomial": "z binomial",
                                                                       "z_simples": "z simples"}.get)
            limite_r = k[1].slider("Limite (desvios): abstenção baixa e liberação manual", 2.0, 6.0, 3.0, 0.5,
                                   key="risco_limite")
            min_aptos_r = k[2].number_input("Ignorar seções com menos aptos que", 0, 500, 50, 10, key="risco_aptos")
            k = st.columns(3)
            lim17_r = k[0].slider("% dos votos após 17h ≥", 5, 50, 15, 5, key="risco_17") / 100
            destoa_r = k[1].checkbox("Voto após 17h: só se destoar da escola", value=True, key="risco_destoa")
            min_crit_r = k[2].radio("Marcada quando cumpre", [1, 2, 3], horizontal=True, key="risco_mincrit",
                                    format_func=lambda n: {1: "≥ 1 critério", 2: "≥ 2", 3: "os 3"}[n])

        mr = pacote["mr"]
        if local_r != "Brasil":
            mr = mr[mr["uf"] == local_r]

        fa, f17, fm = marcar_criterios(mr, medida_r, limite_r, min_aptos_r, lim17_r, destoa_r)
        nc = fa.astype(int) + f17.astype(int) + fm.astype(int)
        marc = nc >= min_crit_r
        grupos = {"Todas as seções com log": pd.Series(True, index=mr.index),
                  f"Marcadas (≥ {min_crit_r} critério{'s' if min_crit_r > 1 else ''})": marc,
                  "Não marcadas": ~marc,
                  "🔻 Abstenção baixa": fa, "⏰ Voto após 17h": f17, "🖐️ Liberação manual": fm,
                  "Cumprem exatamente 1": nc == 1, "Cumprem exatamente 2": nc == 2, "Cumprem os 3": nc == 3}
        grupos = {k_: v_ for k_, v_ in grupos.items() if int(v_.sum()) > 0}
        res_r = resumo_cruzamento(mr, grupos).set_index("grupo")
        nome_m = f"Marcadas (≥ {min_crit_r} critério{'s' if min_crit_r > 1 else ''})"

        # --- resposta em linguagem comum
        if nome_m in res_r.index and "Não marcadas" in res_r.index:
            a_, b_ = res_r.loc[nome_m], res_r.loc["Não marcadas"]
            dif = a_["z_medio"]
            distinto = abs(dif) > a_["ic"] if not np.isnan(a_["ic"]) else False
            onde = "Brasil" if local_r == "Brasil" else local_r
            st.markdown(
                f"Das **{_pt(len(mr))}** seções com log ({onde}), **{_pt(a_['secoes'])}** "
                f"({_pt(a_['secoes'] / len(mr) * 100, 1)}%) foram marcadas como de risco. "
                f"Nelas, o {quem_r} foi de **{_pt(a_['pct1'] * 100, 1)}%** para **{_pt(a_['pct2'] * 100, 1)}%** dos "
                f"votos válidos ({_sp(a_['variacao_pp'])} p.p.); nas demais, de {_pt(b_['pct1'] * 100, 1)}% para "
                f"{_pt(b_['pct2'] * 100, 1)}% ({_sp(b_['variacao_pp'])} p.p.).")
            sinal = "acima" if a_["desvio_pp"] >= 0 else "abaixo"
            st.markdown(
                f"Descontando o que o município inteiro fez, nas marcadas o {quem_r} ficou "
                f"**{_pt(abs(a_['desvio_pp']), 2)} p.p. {sinal} do esperado** "
                f"({_pt(abs(a_['votos_vs_esperado']))} votos {sinal}). "
                + ("Isso é **distinguível do acaso**." if distinto else
                   "Isso **não se distingue do acaso** (o intervalo inclui zero)."))

        # --- tabela
        st.markdown("**Desempenho por grupo de seções**")
        tab_r = res_r.reset_index().rename(columns={
            "grupo": "Grupo", "secoes": "Seções", "pct1": f"{quem_r} % 1º turno", "pct2": f"{quem_r} % 2º turno",
            "variacao_pp": "Variação (p.p.)", "desvio_pp": "Acima/abaixo do esperado (p.p.)",
            "votos_vs_esperado": "Votos acima/abaixo do esperado", "z_medio": "z médio", "ic": "± (95%)",
            "pct_melhora": "% com melhora forte (z ≥ 3)", "pct_piora": "% com piora forte (z ≤ −3)"})
        st.dataframe(tab_r, hide_index=True, width="stretch", column_config={
            f"{quem_r} % 1º turno": st.column_config.NumberColumn(format="percent"),
            f"{quem_r} % 2º turno": st.column_config.NumberColumn(format="percent"),
            "Variação (p.p.)": st.column_config.NumberColumn(format="%+.2f"),
            "Acima/abaixo do esperado (p.p.)": st.column_config.NumberColumn(format="%+.2f"),
            "Votos acima/abaixo do esperado": st.column_config.NumberColumn(format="%+d"),
            "z médio": st.column_config.NumberColumn(format="%+.2f"),
            "± (95%)": st.column_config.NumberColumn(format="%.2f"),
            "% com melhora forte (z ≥ 3)": st.column_config.NumberColumn(format="percent"),
            "% com piora forte (z ≤ −3)": st.column_config.NumberColumn(format="percent")})

        # --- gráfico de pontos com intervalo
        g_plot = res_r.drop(index=["Todas as seções com log"], errors="ignore").iloc[::-1]
        fig = go.Figure(go.Scatter(
            x=g_plot["z_medio"], y=g_plot.index, mode="markers",
            error_x=dict(type="data", array=g_plot["ic"].fillna(0), color="#b8c0cc"),
            marker=dict(size=11, color=[COR_ALTA if z_ > 0 else COR_BAIXA for z_ in g_plot["z_medio"]]),
            customdata=np.stack([g_plot["secoes"], g_plot["desvio_pp"]], axis=1),
            hovertemplate="%{y}<br>z médio %{x:+.2f}<br>%{customdata[0]:,} seções<br>"
                          "%{customdata[1]:+.2f} p.p. vs. esperado<extra></extra>"))
        fig.add_vline(x=0, line_color="black")
        fig.update_layout(title=f"{quem_r}: quanto acima (+) ou abaixo (−) do município, por grupo (z médio ± 95%)",
                          xaxis_title="← pior que o município · z médio do desvio · melhor que o município →",
                          height=max(300, 55 * len(g_plot) + 120), margin=dict(l=10, r=10, t=50, b=10))
        st.plotly_chart(fig, width="stretch")

        # --- lista: seções marcadas com maior melhora
        st.markdown(f"**Seções marcadas em que o {quem_r} mais mudou em relação ao município**")
        k = st.columns(3)
        sentido_r = k[0].radio("Mostrar", ["Melhorou mais", "Piorou mais", "Os dois"], horizontal=True,
                               key="risco_sentido")
        zmin_r = k[1].number_input("|z| mínimo", 0.0, 10.0, 3.0, 0.5, key="risco_zmin")
        min_vot_r = k[2].number_input("Mín. |votos × esperado|", 0, 500, 20, 5, key="risco_minvot")
        sel_r = mr[marc & (mr["z_desvio"].abs() >= zmin_r) & (mr["votos_vs_esperado"].abs() >= min_vot_r)]
        if sentido_r == "Melhorou mais":
            sel_r = sel_r[sel_r["z_desvio"] > 0].sort_values("z_desvio", ascending=False)
        elif sentido_r == "Piorou mais":
            sel_r = sel_r[sel_r["z_desvio"] < 0].sort_values("z_desvio")
        else:
            sel_r = sel_r.reindex(sel_r["z_desvio"].abs().sort_values(ascending=False).index)
        if len(sel_r):
            txt = pd.concat([fa[sel_r.index].map({True: "abstenção baixa", False: ""}),
                             f17[sel_r.index].map({True: "voto após 17h", False: ""}),
                             fm[sel_r.index].map({True: "liberação manual", False: ""})], axis=1)
            sel_r = sel_r.assign(criterios=txt.apply(lambda r: " · ".join(x for x in r if x), axis=1))
        st.write(f"**{len(sel_r):,}** seções marcadas com |z| ≥ {zmin_r:g} ({sentido_r.lower()}).".replace(",", "."))
        cols_l = [c for c in ["uf", "municipio", "zona", "secao", "criterios", "z_desvio", "votos_vs_esperado",
                              "pct1", "pct2", "taxa_abstencao", "pct_apos_17", "pct_manual_cadastrados", "z_manual",
                              "nome_local"] if c in sel_r]
        st.dataframe(sel_r[cols_l], hide_index=True, width="stretch", height=380, column_config={
            "z_desvio": st.column_config.NumberColumn("z do desvio", format="%.2f"),
            "votos_vs_esperado": st.column_config.NumberColumn("votos × esperado", format="%+.0f"),
            "pct1": st.column_config.NumberColumn("% 1", format="percent"),
            "pct2": st.column_config.NumberColumn("% 2", format="percent"),
            "taxa_abstencao": st.column_config.NumberColumn("abstenção 1º turno", format="percent"),
            "pct_apos_17": st.column_config.NumberColumn("% após 17h (1º)", format="percent"),
            "pct_manual_cadastrados": st.column_config.NumberColumn("% liberação manual (1º)", format="percent"),
            "z_manual": st.column_config.NumberColumn("z manual", format="%.2f")})
        st.download_button("⬇️ Baixar lista (CSV)", sel_r[cols_l].rename(columns={"pct1": "% 1", "pct2": "% 2"})
                           .to_csv(index=False, sep=";", decimal=",").encode("utf-8-sig"),
                           f"risco_x_{quem_r.lower()}.csv", "text/csv", key="dl_risco")

        with st.expander("ℹ️ Como ler este cruzamento"):
            st.markdown(
                "- **Seção de risco** = cumpre algum dos três critérios do painel original, medidos no **1º turno**: "
                "abstenção muito baixa, muito voto depois das 17h, muita liberação manual pelo mesário de quem tem "
                "digital cadastrada.\n"
                "- **Acima/abaixo do esperado** compara cada seção com o que o município todo fez entre os turnos "
                "(a \"onda\" local). Assim, melhoras gerais do candidato não contam como anomalia.\n"
                "- **z médio** perto de zero = o grupo se comporta como o resto. Valores bem acima de zero, com o "
                "intervalo (±) longe de zero, indicam que o candidato melhorou *além do município* nesse grupo.\n"
                "- **Associação não é causa.** Seções marcadas têm perfil próprio (zona rural, pouco cadastro biométrico, "
                "fila, idosos). Uma associação pode vir desse perfil, não de irregularidade, e o contrário também vale.\n"
                "- Seções com abstenção muito baixa no 1º turno tendem a ter mais abstenção no 2º (regressão à média), o que "
                "pode afetar a comparação. Veja também a abstenção do 2º turno antes de concluir.\n"
                "- Os logs do 2º turno ainda não foram publicados; quando saírem, dá para medir se as mesmas seções "
                "se repetem como de risco.")
