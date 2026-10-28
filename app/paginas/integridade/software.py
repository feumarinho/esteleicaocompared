"""O software, o firmware ou a mídia da urna mudam o resultado? Comparação DENTRO do mesmo município."""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from app.dados_integridade import aviso_cobertura, integridade


def render(ctx):
    tab, resumo = integridade()
    st.subheader("💾 Software e mídia da urna × resultado")
    st.markdown(
        "Se um software (ou uma carga de dados) tivesse sido alterado para favorecer alguém, as urnas que o usam "
        "teriam resultado diferente das **outras urnas do mesmo município** — mesma cidade, mesmo eleitorado, só "
        "muda o software. É o que se mede aqui: para cada versão, modelo, firmware ou data de carga, a diferença média "
        "contra as demais urnas do município, com intervalo de 95% (erro calculado por município, sem otimismo).")
    aviso_cobertura(resumo)
    s = pd.DataFrame(resumo["software"])
    if s.empty:
        st.info("Sem comparações possíveis.")
        return
    c1, c2 = st.columns(2)
    res = c1.selectbox("Resultado comparado", s["resultado"].unique(), format_func=lambda r: s.loc[s["resultado"] == r, "resultado_rotulo"].iloc[0])
    gru = c2.selectbox("Agrupar urnas por", s["grupo"].unique(), format_func=lambda r: s.loc[s["grupo"] == r, "grupo_rotulo"].iloc[0])
    d = s[(s["resultado"] == res) & (s["grupo"] == gru)].sort_values("nivel")
    if d.empty:
        st.info("Nenhum grupo com seções suficientes (mínimo 100) nesta combinação.")
    else:
        fig = go.Figure(go.Bar(x=d["nivel"], y=d["efeito"], error_y=dict(type="data", array=1.96 * d["ep"]),
                               marker_color="#2a6fb0"))
        fig.add_hline(y=0, line_color="#888")
        fig.update_layout(height=380, margin=dict(l=10, r=10, t=10, b=10), yaxis_title="diferença vs. resto do município",
                          xaxis_title=None, xaxis_type="category")
        st.plotly_chart(fig, width="stretch")
        d = d.assign(**{"IC 95% de": d["efeito"] - 1.96 * d["ep"], "IC 95% até": d["efeito"] + 1.96 * d["ep"]})
        st.dataframe(d[["nivel", "secoes", "municipios", "efeito", "IC 95% de", "IC 95% até", "z"]]
                     .rename(columns={"nivel": "grupo", "secoes": "seções", "municipios": "municípios", "z": "z do efeito"}),
                     hide_index=True, width="stretch",
                     column_config={c: st.column_config.NumberColumn(format="%.3f") for c in ("efeito", "IC 95% de", "IC 95% até", "z")})
    st.markdown("#### Quantos efeitos aparecem 'significativos'?")
    z = s["z"].abs()
    n = int(z.notna().sum())
    rel = s["relevante"] & (z > 3)
    st.markdown(
        f"Foram feitas **{n} comparações**; só por acaso, cerca de **{n * 0.05:.0f}** devem passar de |z| > 2. "
        f"Passaram **{int((z > 2).sum())}**, e **{int((z > 3).sum())}** passaram de 3. Com tantas seções, até diferenças "
        "minúsculas ficam 'significativas'; por isso conta também o **tamanho**: "
        f"**{int(rel.sum())}** comparações têm z > 3 **e** tamanho relevante (≥ 0,1 desvio padrão no z do Lula; "
        "≥ 0,3 ponto percentual nas variações). Um padrão de fraude no software apareceria como o **mesmo grupo** (uma versão, uma carga) destoando em "
        "vários resultados ao mesmo tempo e com tamanho relevante, não como um valor isolado.")
    mais = s.loc[z.sort_values(ascending=False).index[:8], ["grupo_rotulo", "nivel", "resultado_rotulo", "secoes", "efeito", "z", "relevante"]]
    st.dataframe(mais.rename(columns={"grupo_rotulo": "agrupamento", "nivel": "grupo", "resultado_rotulo": "resultado", "secoes": "seções"}),
                 hide_index=True, width="stretch")
    with st.expander("Como foi calculado e o que isto NÃO mostra"):
        st.markdown(
            "- Para cada seção, o resultado é subtraído da média ponderada (pelo comparecimento) do próprio município; a "
            "média dessas diferenças em cada grupo é o 'efeito'. Só entram municípios com mais de um grupo.\n"
            "- Todos os dados vêm de arquivos que a **própria urna** produz. Um software que alterasse votos também "
            "poderia alterar esses registros de forma coerente; estes testes só pegam alteração que **deixe rastro "
            "estatístico** ou **inconsistência entre os registros**.\n"
            "- O modelo de urna e a data de carga se correlacionam com a região e a cidade (urnas mais novas vão para "
            "cidades maiores): é por isso que a comparação é dentro do município.")
