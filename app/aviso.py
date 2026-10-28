"""Diálogo de aviso na abertura do site (ferramenta, dados públicos, créditos ao projeto original)."""
from __future__ import annotations

import streamlit as st

from app.comum import ORIGINAL_AUTOR, ORIGINAL_URL, REPO_URL


def _opcoes_dialogo() -> dict:
    """`dismissible=False` (só o OK fecha) existe nas versões novas do Streamlit; nas antigas, ignora."""
    import inspect
    return {"dismissible": False} if "dismissible" in inspect.signature(st.dialog).parameters else {}


@st.dialog("Aviso", **_opcoes_dialogo())
def aviso_abertura():
    orig = f"[{ORIGINAL_AUTOR}]({ORIGINAL_URL})" if ORIGINAL_URL else f"**{ORIGINAL_AUTOR}**"
    st.markdown(
        "Este site é uma **ferramenta**. Os dados são **públicos** (TSE). As conclusões tiradas deles "
        "são de quem as tira: **não temos nenhuma relação com elas**.\n\n"
        f"O código está em [{REPO_URL.removeprefix('https://')}]({REPO_URL}). Se tiver dúvida de como os "
        "cálculos são feitos, peça à sua IA para ler o código e explicar.\n\n"
        f"Créditos: este projeto é derivado (fork) de [{ORIGINAL_URL.removeprefix('https://')}]({ORIGINAL_URL}), "
        f"de {orig}, que criou a base do painel (abstenção, logs das urnas e critérios de seções atípicas).")
    if st.button("OK", type="primary", width="stretch"):
        st.rerun()


def mostrar_aviso():
    """Abre o diálogo uma vez por visita."""
    if not st.session_state.get("aviso_visto"):
        st.session_state["aviso_visto"] = True
        aviso_abertura()
