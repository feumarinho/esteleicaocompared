"""Painel Streamlit: abstenção, logs das urnas, comparação entre turnos e integridade das urnas.

Estrutura:  app/contexto.py (dados e filtros), app/paginas/<grupo>/<página>.py (cada tela, com `render(ctx)`).
Rodar:      streamlit run painel.py
"""
from __future__ import annotations

import importlib
import importlib.util

import streamlit as st

st.set_page_config(page_title="Abstenção por seção", page_icon="🗳️", layout="wide")

from app import cabecalho  # noqa: E402
from app.aviso import mostrar_aviso  # noqa: E402
from app.comum import TODOS  # noqa: E402
from app.contexto import montar_contexto  # noqa: E402
from app.detalhe import detalhe_secao  # noqa: E402

# grupo -> [(módulo em app.paginas, título, ícone)]
MENU = {
    "1º turno por seção": [
        ("resultado.comparar", "Comparar", "📊"),
        ("resultado.distribuicao", "Distribuição", "📈"),
        ("resultado.funil", "Funil", "🔻"),
        ("risco.sinalizadas", "Sinalizadas", "🚩"),
    ],
    "Critérios dos logs": [
        ("risco.horario", "Horário dos votos", "⏰"),
        ("risco.sem_digital", "Sem digital", "🖐️"),
        ("risco.cruzamento", "Cruzamento", "🔀"),
    ],
    "Comparação entre turnos": [
        ("turnos.comparar_turnos", "1º × 2º turno", "🔁"),
        ("turnos.fluxo", "Fluxo de votos", "🧭"),
        ("turnos.origem_votos", "De onde vêm os votos", "🗳️"),
        ("turnos.risco_melhora", "Risco × melhora", "🎯"),
    ],
}
# páginas opcionais (existem conforme as análises forem sendo adicionadas)
OPCIONAIS = {
    "Integridade das urnas": [
        ("integridade.resumo", "Visão geral", "🧾"),
        ("integridade.conciliacao", "Boletim × RDV × log", "⚖️"),
        ("integridade.software", "Software da urna", "💾"),
        ("integridade.forense", "Testes forenses", "🔬"),
        ("integridade.persistencia", "Persistência do risco", "🔁"),
    ],
    "Contexto histórico": [
        ("historico.referencia", "2018 × 2022 × 2026", "📚"),
    ],
}


def _existe(nome: str) -> bool:
    try:
        return importlib.util.find_spec(f"app.paginas.{nome}") is not None
    except ModuleNotFoundError:
        return False


def _pagina(ctx, nome: str, titulo: str, icone: str) -> st.Page:
    def executar():
        cabecalho.render(ctx)
        importlib.import_module(f"app.paginas.{nome}").render(ctx)
    executar.__name__ = nome.replace(".", "_")
    return st.Page(executar, title=titulo, icon=icone, url_path=nome.replace(".", "-"))


mostrar_aviso()
ctx = montar_contexto()

if ctx.secao != TODOS:
    detalhe_secao(ctx, ctx.df[ctx.df["secao"] == ctx.secao].iloc[0])
    st.stop()

grupos = {g: [(m, t, i) for m, t, i in itens if _existe(m)] for g, itens in {**OPCIONAIS, **MENU}.items()}
ordem = ["Integridade das urnas", "1º turno por seção", "Critérios dos logs", "Comparação entre turnos",
         "Contexto histórico"]
paginas = {g: [_pagina(ctx, *x) for x in grupos[g]] for g in ordem if grupos.get(g)}
st.navigation(paginas).run()
