"""Título do nível atual (Brasil, UF, município) e indicadores resumidos."""
from __future__ import annotations

import streamlit as st

from app.comum import (com_log, hora, pct, resumo)


def render(ctx):
    st.title(ctx.nivel)
    NOME_CRUZ = ctx.NOME_CRUZ
    df = ctx.df
    limite = ctx.limite
    limite_cruz = ctx.limite_cruz
    medida = ctx.medida
    min_aptos = ctx.min_aptos
    min_crit = ctx.min_crit
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

