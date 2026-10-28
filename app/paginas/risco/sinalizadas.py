"""Página «Sinalizadas» do painel."""
from __future__ import annotations

import streamlit as st

from app.detalhe import detalhe_secao
from app.cabecalho import render as cabecalho


def render(ctx):
    cabecalho(ctx)
    df = ctx.df
    lim_17 = ctx.lim_17
    limite = ctx.limite
    medida = ctx.medida
    min_crit = ctx.min_crit
    tem_logs = ctx.tem_logs
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
        detalhe_secao(ctx, sel.iloc[linhas[0]])
