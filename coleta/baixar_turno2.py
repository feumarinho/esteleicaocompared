"""
Lê, por UF, os arquivos de cada urna do 2º turno (boletim de urna, RDV e log) direto dos zips do TSE, por
faixas de bytes (HTTP Range), SEM gravar os zips (são 124 GB): cada seção é lida e resumida na memória.

Resultado por UF (dados/):
    logs_<ano>_t2_<UF>.parquet    métricas de horário dos votos (mesmo formato dos logs do 1º turno; o painel lê)
    integ_<ano>_t2_<UF>.parquet   boletim, RDV, versão do software, mídia de votação e verificações cruzadas

IMPORTANTE: o log do 2º turno é CUMULATIVO (traz também o dia do 1º turno); aqui só vale o dia do 2º turno.

Uso:
    python coleta/baixar_turno2.py --ufs AC                 # um estado
    python coleta/baixar_turno2.py                          # todos, dos menores para os maiores; retoma o que já foi feito
    python coleta/baixar_turno2.py --ufs AC --limite 300    # teste rápido com 300 seções
"""
from __future__ import annotations

import argparse
import struct
import sys
import threading
import time
import zipfile
import zlib
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import pandas as pd
import requests

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from analise.leitores_urna import DIAS_ELEICAO, PRESIDENTE, ler_bu, ler_rdv, resumir_log  # noqa: E402
from analise.logs_urna import consolidar_secoes, ler_eventos, extrair_logd  # noqa: E402
from download_tse import ArquivoRemoto, baixar_faixa, tamanho_remoto  # noqa: E402

PASTA = RAIZ / "dados"
URL = ("https://cdn.tse.jus.br/estatistica/sead/eleicoes/eleicoes{ano}/arqurnatot/"
       "bu_imgbu_logjez_rdv_vscmr_{ano}_{turno}t_{uf}.zip")
# dos menores para os maiores: o que já terminou fica aproveitável se o processo for interrompido
ORDEM = ["AC", "RR", "AP", "TO", "RO", "SE", "DF", "RN", "MS", "MT", "AL", "AM", "PI", "ES", "PB", "GO", "MA", "SC",
         "PA", "PE", "CE", "RS", "PR", "BA", "RJ", "MG", "SP"]
SUFIXOS = {"-bu.dat": "bu", "-rdv.dat": "rdv", "-log.jez": "log"}
FOLGA_BLOCO = 32 * 1024     # junta arquivos vizinhos se o "vão" entre eles for menor que isso
_local = threading.local()


# ------------------------------------------------------------------ leitura do zip remoto
def listar_secoes(url: str) -> tuple[int, dict]:
    """{prefixo da seção: {'bu'|'rdv'|'log': (nome, offset, tam_comprimido, método, crc)}} lendo só o diretório central."""
    s = requests.Session()
    tamanho = tamanho_remoto(s, url)
    with zipfile.ZipFile(ArquivoRemoto(url, s, tamanho)) as z:
        infos = z.infolist()
    grupos: dict = defaultdict(dict)
    for i in infos:
        for suf, chave in SUFIXOS.items():
            if i.filename.endswith(suf):
                grupos[i.filename[: -len(suf)]][chave] = (i.filename, i.header_offset, i.compress_size,
                                                          i.compress_type, i.CRC)
    return tamanho, dict(grupos)


def _sessao() -> requests.Session:
    if not hasattr(_local, "s"):
        _local.s = requests.Session()
    return _local.s


def _extrair(buf: bytes, ini: int, membro: tuple, url: str, tamanho: int) -> bytes:
    nome, off, comp, metodo, crc = membro
    o = off - ini
    if buf[o:o + 4] != b"PK\x03\x04":
        raise IOError(f"cabeçalho local inválido em {nome}")
    n, x = struct.unpack("<HH", buf[o + 26:o + 30])
    ini_dados = o + 30 + n + x
    dados = buf[ini_dados:ini_dados + comp]
    if len(dados) < comp:  # campo "extra" maior que a folga: busca o resto
        falta = comp - len(dados)
        a = off + 30 + n + x + len(dados)
        dados += baixar_faixa(_sessao(), url, a, a + falta - 1)
    conteudo = dados if metodo == zipfile.ZIP_STORED else zlib.decompress(dados, -15)
    if zlib.crc32(conteudo) & 0xFFFFFFFF != crc:
        raise IOError(f"CRC não confere em {nome}")
    return conteudo


def baixar_membros(url: str, tamanho: int, membros: dict) -> tuple[dict, int]:
    """Baixa os arquivos de UMA seção juntando em uma só requisição os que estão vizinhos no zip."""
    ordenados = sorted(membros.items(), key=lambda kv: kv[1][1])
    blocos, atual = [], [ordenados[0]]
    for item in ordenados[1:]:
        fim_prev = atual[-1][1][1] + 30 + len(atual[-1][1][0]) + atual[-1][1][2]
        if item[1][1] - fim_prev <= FOLGA_BLOCO:
            atual.append(item)
        else:
            blocos.append(atual)
            atual = [item]
    blocos.append(atual)
    saida, baixados = {}, 0
    for bloco in blocos:
        ini = bloco[0][1][1]
        ult = bloco[-1][1]
        fim = min(ult[1] + 30 + len(ult[0]) + 512 + ult[2] + 1024, tamanho) - 1
        buf = baixar_faixa(_sessao(), url, ini, fim)
        baixados += len(buf)
        for chave, m in bloco:
            saida[chave] = _extrair(buf, ini, m, url, tamanho)
    return saida, baixados


# ------------------------------------------------------------------ uma seção
def _achatar_bu_rdv(bu: dict, rdv: dict, turno: int) -> dict:
    out = {k: v for k, v in bu.items() if k != "bu_cargos"}
    cod_p = PRESIDENTE[turno]
    cargos = bu["bu_cargos"]
    p = cargos.get(cod_p)
    outros = [c for c in cargos if c != cod_p]
    g = cargos[outros[0]] if outros else None
    if p is not None:
        out.update(bu_aptos=p["aptos"], bu_p_13=p["cand"].get(13, 0), bu_p_22=p["cand"].get(22, 0),
                   bu_p_outros=sum(q for n, q in p["cand"].items() if n not in (13, 22)),
                   bu_p_branco=p["branco"], bu_p_nulo=p["nulo"])
    if g is not None:
        out.update(bu_g_cod=outros[0], bu_g_total=sum(g["cand"].values()) + g["branco"] + g["nulo"],
                   bu_g_branco=g["branco"], bu_g_nulo=g["nulo"])
    rp = rdv.get(cod_p)
    if rp is not None:
        out.update(rdv_p_13=rp["cand"].get("13", 0), rdv_p_22=rp["cand"].get("22", 0),
                   rdv_p_outros=sum(q for n, q in rp["cand"].items() if n not in ("13", "22")),
                   rdv_p_branco=rp["branco"], rdv_p_nulo=rp["nulo"], rdv_p_nulo_susp=rp["nulo_susp"],
                   rdv_nulo_p_00=rp["nulos_digitados"].get("00", 0))
        if outros and outros[0] in rdv:
            nums_gov = set(rdv[outros[0]]["cand"])
            out["rdv_nulo_p_dig_gov"] = sum(q for n, q in rp["nulos_digitados"].items() if n in nums_gov)
    rg = rdv.get(outros[0]) if outros else None
    if rg is not None:
        out.update(rdv_g_total=sum(rg["cand"].values()) + rg["branco"] + rg["nulo"],
                   rdv_g_branco=rg["branco"], rdv_g_nulo=rg["nulo"])
    # conferências cruzadas
    if p is not None and rp is not None:
        iguais = (p["branco"] == rp["branco"] and p["nulo"] == rp["nulo"]
                  and {str(n): q for n, q in p["cand"].items()} == dict(rp["cand"]))
        if g is not None and rg is not None:
            # outro cargo: compara os totais (consultas sim/não têm numeração que o boletim não discrimina)
            iguais = iguais and (g["branco"] == rg["branco"] and g["nulo"] == rg["nulo"]
                                 and sum(g["cand"].values()) == sum(rg["cand"].values()))
        out["chk_bu_rdv"] = bool(iguais)
    if p is not None:
        out["chk_bu_comp"] = (sum(p["cand"].values()) + p["branco"] + p["nulo"]) == bu["bu_comparecimento"]
    return out


def processar_secao(url: str, tamanho: int, prefixo: str, membros: dict, turno: int, dia: str):
    uf = prefixo.split("/")[-1][6:8].upper()
    mun, zona, secao = int(prefixo[-13:-8]), int(prefixo[-8:-4]), int(prefixo[-4:])
    chave = (mun, zona, secao)
    bruto, n_bytes = baixar_membros(url, tamanho, membros)
    linha = {"uf": uf, "cd_municipio": mun, "zona": zona, "secao": secao}
    erros = []
    try:
        texto = extrair_logd(bruto["log"])
        ev = ler_eventos(texto, dia)
        linha.update(resumir_log(texto, DIAS_ELEICAO))
        r = {"chave": chave, **ev}
    except Exception as e:
        erros.append(f"log: {type(e).__name__}: {e}")
        r = None
    try:
        bu = ler_bu(bruto["bu"])
        rdv = ler_rdv(bruto["rdv"])
        linha.update(_achatar_bu_rdv(bu, rdv, turno))
    except Exception as e:
        erros.append(f"bu/rdv: {type(e).__name__}: {e}")
    d = f"d{turno}_"
    if "bu_comparecimento" in linha and f"{d}votos" in linha:
        linha["chk_log_bu"] = linha[f"{d}votos"] == linha["bu_comparecimento"]
        linha["chk_conf_pres"] = linha[f"{d}conf_pres"] == linha[f"{d}votos"]
    if erros:
        linha["erro"] = " ; ".join(erros)
    return linha, r, n_bytes


def _lote(args):
    url, tamanho, itens, turno, dia = args
    saida = []
    for prefixo, membros in itens:
        for tentativa in range(3):
            try:
                saida.append(processar_secao(url, tamanho, prefixo, membros, turno, dia))
                break
            except Exception as e:  # falha de rede: tenta de novo
                if tentativa == 2:
                    saida.append(({"uf": prefixo.split("/")[-1][6:8].upper(), "cd_municipio": int(prefixo[-13:-8]),
                                   "zona": int(prefixo[-8:-4]), "secao": int(prefixo[-4:]),
                                   "erro": f"download: {type(e).__name__}: {e}"}, None, 0))
                else:
                    time.sleep(2 ** tentativa)
    return saida


# ------------------------------------------------------------------ por UF
def processar_uf(uf: str, ano: int, turno: int, processos: int, limite: int | None, lote: int) -> bool:
    url = URL.format(ano=ano, turno=turno, uf=uf)
    t0 = time.time()
    try:
        tamanho, grupos = listar_secoes(url)
    except FileNotFoundError:
        print(f"  {uf}: arquivo ainda não publicado (404)")
        return False
    itens = [(p, m) for p, m in sorted(grupos.items()) if {"bu", "rdv", "log"} <= m.keys()]
    sem = len(grupos) - len(itens)
    if limite:
        itens = itens[:limite]
    print(f"  {uf}: zip de {tamanho / 1e6:,.0f} MB, {len(itens):,} seções" + (f" ({sem} sem os 3 arquivos)" if sem else ""))
    lotes = [(url, tamanho, itens[i:i + lote], turno, DIAS_ELEICAO[turno]) for i in range(0, len(itens), lote)]
    linhas, por_secao, baixados, feitos = [], defaultdict(list), 0, 0
    with ProcessPoolExecutor(max_workers=processos) as ex:
        futuros = [ex.submit(_lote, a) for a in lotes]
        for f in as_completed(futuros):
            for linha, r, n_bytes in f.result():
                linhas.append(linha)
                baixados += n_bytes
                if r is not None:
                    por_secao[r["chave"]].append(r)
                feitos += 1
            dt = max(time.time() - t0, 1e-6)
            print(f"\r    {feitos:,}/{len(itens):,} seções  ({baixados / dt / 1e6:,.1f} MB/s, {feitos / dt:,.0f} seções/s)   ",
                  end="", flush=True)
    print()
    integ = pd.DataFrame(linhas)
    n_err = int(integ["erro"].notna().sum()) if "erro" in integ else 0
    logs = consolidar_secoes(por_secao, uf)
    for col in integ.columns:  # textos repetidos (modelo, versão, computador da mídia...) viram categorias: arquivo menor
        if col != "erro" and pd.api.types.is_string_dtype(integ[col]) and not pd.api.types.is_bool_dtype(integ[col]):
            integ[col] = integ[col].astype("category")
    PASTA.mkdir(exist_ok=True)
    suf = "_TESTE" if limite else ""     # teste parcial nunca ocupa o nome oficial (senão a UF seria pulada depois)
    integ.to_parquet(PASTA / f"integ_{ano}_t{turno}_{uf}{suf}.parquet", index=False, compression="zstd")
    if not logs.empty:
        logs.to_parquet(PASTA / f"logs_{ano}_t{turno}_{uf}{suf}.parquet", index=False, compression="zstd")
    ok = lambda c: f"{integ[c].mean() * 100:.2f}%" if c in integ else "—"
    print(f"    {n_err} com erro | BU=RDV em {ok('chk_bu_rdv')} | BU soma=comparecimento em {ok('chk_bu_comp')} | "
          f"log=BU em {ok('chk_log_bu')} | {time.time() - t0:,.0f} s")
    for e in integ["erro"].dropna().unique()[:3] if "erro" in integ else []:
        print("    !", str(e)[:160])
    return n_err == 0


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--ano", type=int, default=2026)
    p.add_argument("--turno", type=int, default=2, choices=[2], help="só o 2º turno (o 1º já tem os logs processados)")
    p.add_argument("--ufs", nargs="+", type=str.upper, default=ORDEM)
    p.add_argument("--processos", type=int, default=20, help="conexões/processos simultâneos (IO: pode passar do nº de CPUs)")
    p.add_argument("--lote", type=int, default=8, help="seções por tarefa")
    p.add_argument("--limite", type=int, help="processa só as N primeiras seções (teste)")
    p.add_argument("--refazer", action="store_true")
    a = p.parse_args()
    for uf in a.ufs:
        destino = PASTA / f"integ_{a.ano}_t{a.turno}_{uf}.parquet"
        if destino.exists() and not a.refazer and not a.limite:
            print(f"{uf}: já processado ({destino.name})")
            continue
        print(f"=== {uf} ({a.ano}, {a.turno}º turno) ===")
        try:
            processar_uf(uf, a.ano, a.turno, a.processos, a.limite, a.lote)
        except KeyboardInterrupt:
            print("\nInterrompido. Rode o mesmo comando para continuar pelas UFs que faltam.")
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
