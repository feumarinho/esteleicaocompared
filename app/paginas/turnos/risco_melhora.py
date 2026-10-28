"""Página «Risco × melhora» do painel."""
from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from app.comum import (COR_ALTA, COR_BAIXA, NOMES_CURTOS, _pt, arquivo_risco, candidatos_risco, carregar_risco,
                        marcar_criterios, resumo_cruzamento)


def _sp(x: float, casas: int = 1) -> str:
    """Número com sinal explícito: +4,9 / −0,3."""
    return ("+" if x >= 0 else "−") + _pt(abs(x), casas)


def render(ctx):
    arquivo = ctx.arquivo
    ano_r = arquivo.stem.split("_")[1]
    if not arquivo_risco(ano_r).exists():
        st.info("Esta aba lê um arquivo pré-calculado que ainda não existe. Gere-o (precisa dos logs do 1º turno): "
                "`python baixar_logs.py --turno 1` e depois `python gerar_resultado_risco.py`.")
    else:
        st.subheader("Seções de risco do 1º turno × desempenho no 2º")
        st.caption("Os critérios de risco vêm dos **logs das urnas do 1º turno** (os do 2º turno estão na página **Integridade → Persistência do risco**). "
                   "Aqui eles são cruzados com o desempenho do candidato no 2º turno em relação ao seu município. "
                   "Os dados desta aba são um resultado pré-calculado (exterior fora).")
        cand_r = st.session_state.get("risco_cand", candidatos_risco(ano_r)[0])
        pacote = carregar_risco(ano_r, cand_r, (arquivo_risco(ano_r).stat().st_mtime,))
        if pacote["n_ufs_log"] < pacote["n_ufs"]:
            st.warning(f"O arquivo pré-calculado cobre {pacote['n_ufs_log']} de {pacote['n_ufs']} UFs (26 estados + DF).")

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
                + (("Isso é estatisticamente distinguível do acaso, mas a diferença é **pequena** "
                    "(menos de 0,25 p.p.): com tantas seções, até desvios mínimos aparecem como significativos."
                    if abs(a_["desvio_pp"]) < 0.25 else "Isso é **distinguível do acaso** e de tamanho relevante.")
                   if distinto else "Isso **não se distingue do acaso** (o intervalo inclui zero)."))

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
                "- Os logs do 2º turno já estão disponíveis: a página **Integridade das urnas → Persistência do risco** mostra "
                "se as mesmas seções se repetem como de risco.")
