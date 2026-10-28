"""Leitura dos resultados estáticos de `coleta/gerar_integridade.py` (resultados/integridade_<ano>.*)."""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import streamlit as st

RESULTADOS = Path(__file__).resolve().parent.parent / "resultados"


@st.cache_resource(show_spinner="Carregando resultados da integridade…")
def carregar_integridade(ano: int = 2026, assinatura: tuple = ()):
    """(tabela por seção, resumos) ou None se os arquivos ainda não existem."""
    p, j = RESULTADOS / f"integridade_{ano}.parquet", RESULTADOS / f"integridade_{ano}.json"
    if not (p.exists() and j.exists()):
        return None
    return pd.read_parquet(p), json.loads(j.read_text(encoding="utf-8"))


def integridade():
    """Carrega (com cache invalidado quando os arquivos mudam) e mostra aviso se não existirem."""
    p = RESULTADOS / "integridade_2026.parquet"
    r = carregar_integridade(2026, (p.stat().st_mtime,) if p.exists() else ())
    if r is None:
        st.info("Os resultados de integridade ainda não foram gerados. Rode `python coleta/baixar_turno2.py` e depois "
                "`python coleta/gerar_integridade.py` (ou atualize o repositório com `git pull`).")
        st.stop()
    return r


def aviso_cobertura(resumo: dict):
    n = len(resumo["ufs"])
    if n < 27:
        st.warning(f"⚠️ Resultados parciais: {n} de 27 UFs lidas ({', '.join(resumo['ufs'])}). "
                   "As demais entram quando a leitura do 2º turno terminar.")
