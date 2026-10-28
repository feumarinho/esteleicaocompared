"""Página «1º × 2º turno» do painel."""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from app.comum import (COR_ALTA, COR_NORMAL, NOMES_CURTOS, TODOS, amostrar_fundo, arquivos_turnos, candidatos_turnos,
                        carregar_comparacao, histograma, pct)


def render(ctx):
    arquivo = ctx.arquivo
    filho = ctx.filho
    incluir_zz = ctx.incluir_zz
    mun = ctx.mun
    rotulo = ctx.rotulo
    uf = ctx.uf
    zona = ctx.zona
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
