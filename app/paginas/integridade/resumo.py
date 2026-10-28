"""Visão geral da área de integridade das urnas."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from app.dados_integridade import aviso_cobertura, integridade


def render(ctx):
    tab, resumo = integridade()
    st.subheader("🧾 Integridade das urnas: visão geral")
    st.markdown(
        "O TSE publica, para cada urna do 2º turno, **três arquivos independentes**: o boletim de urna (contagem), o "
        "registro digital do voto e o log. Esta área lê os três para **todas as seções** e procura incoerências ou "
        "padrões estatísticos que poderiam indicar problema — inclusive no **software** da urna. Nenhum teste aqui "
        "prova fraude: um resultado 'limpo' também não prova que não houve, porque todos os arquivos vêm da própria urna.")
    aviso_cobertura(resumo)
    c = pd.DataFrame(resumo["conciliacao"])
    tot = c.drop(columns="uf").sum()
    k = st.columns(4)
    k[0].metric("Seções lidas", f"{int(tot['secoes']):,}".replace(",", "."))
    k[1].metric("Boletim = RDV", f"{1 - tot['bu_diferente_rdv'] / tot['secoes']:.2%}")
    k[2].metric("Boletim = resultado oficial", f"{1 - tot['bu_diferente_oficial'] / max(tot['secoes'] - tot['sem_oficial'], 1):.2%}")
    k[3].metric("Log = boletim (votos)", f"{1 - tot['log_diferente_bu'] / tot['secoes']:.2%}")

    s = pd.DataFrame(resumo["software"])
    z = s["z"].abs().dropna()
    dg = [(d["lula_t2"] or {}).get("p") for d in resumo["forense"]["digitos"][1:]] + [(d["flavio_t2"] or {}).get("p") for d in resumo["forense"]["digitos"][1:]]
    dg = [x for x in dg if x is not None]
    p = pd.DataFrame(resumo["persistencia"])
    comp = resumo["composicao"]
    st.markdown("### O que foi encontrado até agora")
    st.markdown(
        f"- **Coerência dos registros:** o boletim de urna bate com o RDV e com o resultado oficial em praticamente todas as seções "
        f"({int(tot['bu_diferente_rdv'])} diferenças de {int(tot['secoes']):,} entre BU e RDV; {int(tot['bu_diferente_oficial'])} entre BU e oficial). ".replace(",", ".")
        + f"Os logs divergem do comparecimento em {tot['log_diferente_bu'] / tot['secoes']:.2%} das seções (perda de linhas, urna trocada).\n"
        f"- **Software:** {len(comp['log_modelo'])} modelos de urna, {len(comp['log_versao'])} versão(ões) de software e "
        f"{len(comp['log_uefi'])} firmware(s) nos logs. Em {len(z)} comparações dentro do município, {int((z > 2).sum())} passaram de |z|>2 "
        f"(esperado por acaso: ~{len(z) * 0.05:.0f}) e {int((z > 3).sum())} de |z|>3; só {int((s['relevante'] & (s['z'].abs() > 3)).sum())} também têm tamanho relevante.\n"
        f"- **Dígitos finais:** {sum(1 for x in dg if x < 0.05)} de {len(dg)} testes com p<0,05 (esperado por acaso: ~{len(dg) * 0.05:.0f}).\n"
        f"- **Persistência do risco:** as seções de abstenção baixa no 1º turno repetem no 2º em "
        f"{p.loc[p.criterio == 'Abstenção baixa', 't2_dado_t1'].iloc[0]:.0%} dos casos (contra {p.loc[p.criterio == 'Abstenção baixa', 't2_dado_nao_t1'].iloc[0]:.1%} das demais): é uma característica estável da seção.")
    st.markdown("### Páginas desta área")
    st.markdown(
        "- **⚖️ Boletim × RDV × log**: conferência dos registros e lista das seções com diferença.\n"
        "- **💾 Software da urna**: modelo, versão, firmware, data da carga e mídia contra o resultado, dentro do município.\n"
        "- **🔬 Testes forenses**: último dígito dos votos e correlação participação × voto.\n"
        "- **🔁 Persistência do risco**: as seções de risco do 1º turno voltam a se destacar no 2º? E como o Lula foi nelas?")
    with st.expander("O que estes testes conseguem — e não conseguem — detectar"):
        st.markdown(
            "**Conseguem:** incoerência entre os registros de uma mesma urna; seções ou grupos de urnas (versão, carga, "
            "modelo) com resultado fora do padrão do município; manipulação grosseira de totais (dígitos); acréscimo de "
            "votos de um só lado (impressão digital participação × voto).\n\n"
            "**Não conseguem:** descartar um software que altere o voto **e** os três registros de forma coerente "
            "(isso exige auditoria do código e verificação da assinatura digital por quem tem as chaves — o log registra "
            "o resultado da verificação de assinatura, mas o hash por linha não é verificável com os dados públicos); "
            "nem distinguir fraude de uma mudança real de comportamento do eleitor.")
