"""Dados e filtros globais do painel (barra lateral). `montar_contexto()` devolve tudo o que as páginas usam."""
from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pandas as pd
import streamlit as st

from app.comum import (CRITERIOS, PASTA, TODOS, arquivos_logs, carregar, com_log, marcar_criterios, resumo)


def montar_contexto():
    # ---------------------------------------------------------------- dados
    arquivos = sorted(PASTA.glob("secoes_*.parquet"), reverse=True)
    arquivos.sort(key=lambda a: -len(arquivos_logs(a)))   # abre no turno com mais logs processados (todas as abas funcionam)
    if not arquivos:
        st.error("Nenhum dado encontrado em `dados/`. Os dados processados vêm no repositório: atualize-o (`git pull`) "
                 "ou, para gerar do zero, rode `python coleta/baixar_dados.py`.")
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

        with st.expander("⚙️ Critérios de sinalização e cruzamento", expanded=False):
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
                               "Rode `python coleta/baixar_logs.py --refazer`.")
            else:
                criterios, limite_cruz = ["Abstenção baixa", "Votação tardia"], 2.0
                if arquivo.stem.endswith("_t2"):
                    st.caption("Logs das urnas do 2º turno ainda não processados em `dados/` "
                               "(rode `python coleta/baixar_turno2.py`). Para ver os critérios de risco, "
                               "escolha o 1º turno em \"Eleição / turno\".")
                else:
                    st.caption("Sem logs de urna para este turno em `dados/`.")

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

    nivel = ("Brasil" if uf == TODOS else uf if mun == TODOS else
             f"{df['municipio'].iloc[0]} / {uf}" + (f" · Zona {zona}" if zona != TODOS else ""))
    r = resumo(df).iloc[0]
    dl = com_log(df)
    if uf == TODOS:
        filho, rotulo = ["uf"], "uf"
    elif mun == TODOS:
        filho, rotulo = ["cd_municipio", "municipio"], "municipio"
    elif zona == TODOS:
        filho, rotulo = ["zona"], "zona"
    else:
        filho, rotulo = (["local"], "local") if "local" in df else (["secao"], "secao")
    if arquivo.stem.endswith("_t2"):
        SEM_LOGS = ("Os logs deste turno ainda não foram processados em `dados/` para este nível. Escolha o **1º turno** em "
                    "\"Eleição / turno\" (barra lateral) ou veja as páginas do grupo **Integridade das urnas**.")
    else:
        SEM_LOGS = ("Ainda não há logs de urna para este nível em `dados/`. Para gerá-los: `python coleta/baixar_logs.py --turno 1` "
                    "(atenção: são dezenas de GB de download; os dados processados normalmente já vêm no repositório).")

    return SimpleNamespace(
        NOME_CRUZ=NOME_CRUZ,
        SEM_LOGS=SEM_LOGS,
        arquivo=arquivo,
        arquivos=arquivos,
        assinatura=assinatura,
        base=base,
        calcular_score=calcular_score,
        criterios=criterios,
        df=df,
        disponiveis=disponiveis,
        dl=dl,
        filho=filho,
        incluir_zz=incluir_zz,
        lim_17=lim_17,
        limite=limite,
        limite_cruz=limite_cruz,
        medida=medida,
        min_aptos=min_aptos,
        min_crit=min_crit,
        mun=mun,
        nivel=nivel,
        r=r,
        rotulo=rotulo,
        secao=secao,
        sinalizar=sinalizar,
        so_destoa=so_destoa,
        tem_digital=tem_digital,
        tem_logs=tem_logs,
        uf=uf,
        ufs=ufs,
        zona=zona,
    )
