"""
Leitores dos arquivos de cada urna publicados pelo TSE (zips "arqurnatot"): boletim de urna (bu.dat),
registro digital do voto (rdv.dat) e métricas "de saúde" do log (log.jez).

Formato (descoberto lendo os arquivos e validado contra os totais oficiais por seção):

bu.dat   ASN.1/BER. Dentro de um OCTET STRING vem o boletim propriamente dito:
         cabeçalho (data, eleição), turno, versão do software e dados da mídia de votação
         (urna, computador que gerou a mídia, TPM, data), identificação da seção, abertura e
         encerramento, comparecimento e, para cada cargo, uma lista de apurações:
             [C1] tipo (1 = candidato, 2 = branco, 3 = nulo)  [C2] quantidade de votos
             [C3] número do candidato  [U2] ordem  [U4] assinatura

rdv.dat  ASN.1/BER. Para cada cargo, uma lista (embaralhada) com UM registro por voto:
             [U10] tipo (2 = candidato, 3 = branco, 4 = nulo, 6 = nulo por suspensão)  [U18] número
         Os nulos (tipo 4) guardam o número que o eleitor digitou. O tipo 6 é o voto nulo atribuído pela urna
         ("Atribuido voto nulo por suspensão [Presidente]"): o eleitor votou só em parte e o mesário o suspendeu;
         o boletim soma esses votos aos nulos.

O código de eleição dos cargos varia por turno; o da Presidência no 2º turno de 2026 é 6258
(1º turno: 6257). Os demais blocos são tratados como "governador" (só totais).
"""
from __future__ import annotations

import re
from collections import Counter

import numpy as np

from .logs_urna import MSG_MANUAL, MSG_VOTO

PRESIDENTE = {1: 6257, 2: 6258}          # código de eleição do BU/RDV para Presidente em cada turno (2026)
DIAS_ELEICAO = {1: "04/10/2026", 2: "25/10/2026"}


# ------------------------------------------------------------------ BER mínimo
def _nos(b: bytes, i: int = 0, fim: int | None = None):
    """Itera (classe, construído, número, início do corpo, comprimento)."""
    fim = len(b) if fim is None else fim
    while i < fim:
        t = b[i]
        i += 1
        classe, construido, num = t >> 6, bool(t & 0x20), t & 0x1F
        if num == 0x1F:
            num = 0
            while True:
                x = b[i]
                i += 1
                num = (num << 7) | (x & 0x7F)
                if not x & 0x80:
                    break
        n = b[i]
        i += 1
        if n & 0x80:
            k = n & 0x7F
            n = int.from_bytes(b[i:i + k], "big")
            i += k
        yield classe, construido, num, i, n
        i += n


class No:
    """Nó BER já decodificado. `filhos` para construídos; `valor` (bytes) para primitivos."""
    __slots__ = ("classe", "num", "filhos", "valor")

    def __init__(self, classe, num, filhos=None, valor=b""):
        self.classe, self.num, self.filhos, self.valor = classe, num, filhos, valor

    def is_(self, classe, num):
        return self.classe == classe and self.num == num

    @property
    def inteiro(self) -> int:
        return int.from_bytes(self.valor, "big")

    @property
    def texto(self) -> str:
        return self.valor.decode("latin-1")


def decodificar(b: bytes, i: int = 0, fim: int | None = None) -> list[No]:
    out = []
    for classe, construido, num, ini, n in _nos(b, i, fim):
        if construido:
            out.append(No(classe, num, filhos=decodificar(b, ini, ini + n)))
        else:
            out.append(No(classe, num, valor=b[ini:ini + n]))
    return out


def _achar(no: No, classe: int, num: int):
    """Primeiro descendente (busca em profundidade) com a etiqueta pedida."""
    for f in no.filhos or ():
        if f.is_(classe, num):
            return f
        if f.filhos:
            r = _achar(f, classe, num)
            if r is not None:
                return r
    return None


def _cdata(s: str) -> str:
    """'20261025T150358' -> '2026-10-25T15:03:58'."""
    return f"{s[0:4]}-{s[4:6]}-{s[6:8]}T{s[9:11]}:{s[11:13]}:{s[13:15]}" if len(s) >= 15 else s


# ------------------------------------------------------------------ boletim de urna
def _entradas_bu(no: No, acum: list):
    """Coleta as apurações [C1 tipo][C2 votos][C3 número]... dentro de um cargo."""
    f = no.filhos or ()
    if len(f) >= 2 and f[0].is_(2, 1) and f[1].is_(2, 2):
        numero = None
        for x in f:
            if x.is_(2, 3) and x.filhos:
                numero = x.filhos[0].inteiro
        acum.append((f[0].inteiro, f[1].inteiro, numero))
        return
    for x in f:
        if x.filhos:
            _entradas_bu(x, acum)


def ler_bu(b: bytes) -> dict:
    """Campos do boletim de urna. Lança exceção se o arquivo não tiver a estrutura esperada."""
    raiz = decodificar(b)[0]
    octeto = next(x for x in raiz.filhos if x.is_(0, 4))
    bu = decodificar(octeto.valor)[0]
    f = bu.filhos
    out = {"bu_turno": next(x for x in f if x.is_(0, 10)).inteiro}
    cab = f[0]
    out["bu_emissao"] = _cdata(cab.filhos[0].texto)
    # versão, urna, mídia de votação
    info = next(x for x in f if x.is_(0, 16) and _achar(x, 0, 27) is not None and _achar(x, 0, 2) is not None)
    v = next(x for x in info.filhos if x.is_(0, 27))
    out["bu_versao"] = v.texto
    pc_tpm_inst = next((x for x in _descendentes(info) if x.is_(0, 16) and len(x.filhos) == 3
                        and all(y.is_(0, 27) for y in x.filhos)), None)
    if pc_tpm_inst is not None:
        out["bu_midia_pc"], out["bu_midia_tpm"], out["bu_midia_inst"] = (y.texto for y in pc_tpm_inst.filhos)
    textos = [x.texto for x in _descendentes(info) if x.is_(0, 27)]
    datas = [t for t in textos if re.fullmatch(r"\d{8}T\d{6}", t)]
    out["bu_carga_dt"] = _cdata(datas[0]) if datas else None
    urna = next((x for x in _descendentes(info) if x.is_(0, 2) and len(x.valor) == 3), None)
    out["bu_urna"] = urna.inteiro if urna is not None else None
    # identificação da seção (município, zona, local, seção)
    ident = next(x for x in f if x.is_(0, 16) and len(x.filhos) == 3
                 and x.filhos[0].is_(0, 16) and x.filhos[1].is_(0, 2) and x.filhos[2].is_(0, 2))
    out["bu_mun"], out["bu_zona"] = ident.filhos[0].filhos[0].inteiro, ident.filhos[0].filhos[1].inteiro
    out["bu_local"], out["bu_secao"] = ident.filhos[1].inteiro, ident.filhos[2].inteiro
    # abertura e encerramento
    horarios = next(x for x in f if x.is_(2, 0) and len(x.filhos) == 2 and x.filhos[0].is_(0, 27))
    out["bu_abertura"], out["bu_encerramento"] = _cdata(horarios.filhos[0].texto), _cdata(horarios.filhos[1].texto)
    # comparecimento e detalhamento da identificação
    comp = next(x for x in f if x.is_(0, 2))
    out["bu_comparecimento"] = comp.inteiro
    det = next((x for x in f if x.is_(2, 1) and len(x.filhos or ()) == 3), None)
    if det is not None:
        out["bu_ident_a"], out["bu_ident_b"], out["bu_ident_c"] = (y.inteiro for y in det.filhos)
    # cargos: lista de blocos [U2 código][U2 aptos]...
    cargos = next(x for x in f if x.is_(0, 16) and x.filhos
                  and all(c.is_(0, 16) and len(c.filhos) >= 5 and c.filhos[0].is_(0, 2) for c in x.filhos))
    out["bu_cargos"] = {}
    for bloco in cargos.filhos:
        cod = bloco.filhos[0].inteiro
        aptos = bloco.filhos[1].inteiro if bloco.filhos[1].is_(0, 2) else None
        ent: list = []
        _entradas_bu(bloco, ent)
        cand = {n: q for t, q, n in ent if t == 1 and n is not None}
        out["bu_cargos"][cod] = {"aptos": aptos, "cand": cand,
                                  "branco": sum(q for t, q, n in ent if t == 2),
                                  "nulo": sum(q for t, q, n in ent if t == 3)}
    return out


def _descendentes(no: No):
    for x in no.filhos or ():
        yield x
        if x.filhos:
            yield from _descendentes(x)


# ------------------------------------------------------------------ registro digital do voto
def ler_rdv(b: bytes) -> dict:
    """Apuração refeita voto a voto: {código do cargo: {"cand": Counter, "branco": n, "nulo": n, "nulos_digitados": Counter}}."""
    raiz = decodificar(b)[0]
    bloco_cargos = next(x for x in _descendentes(raiz) if x.is_(2, 1) and x.filhos)
    out = {}
    for cargo in bloco_cargos.filhos:
        cod = cargo.filhos[0].inteiro
        cand, dig = Counter(), Counter()
        branco = nulo = susp = 0
        for x in _descendentes(cargo):
            f = x.filhos
            if f and len(f) <= 2 and all(y.is_(0, 10) or y.is_(0, 18) for y in f) and f[0].is_(0, 10):
                tipo = f[0].inteiro
                numero = f[1].texto if len(f) > 1 else None
                if tipo == 2:
                    cand[numero] += 1
                elif tipo == 3:
                    branco += 1
                elif tipo == 4:
                    nulo += 1
                    dig[numero] += 1
                elif tipo == 6:
                    nulo += 1
                    susp += 1
        out[cod] = {"cand": cand, "branco": branco, "nulo": nulo, "nulo_susp": susp, "nulos_digitados": dig}
    return out


# ------------------------------------------------------------------ métricas "de saúde" do log
RE_TPL = re.compile(r"\d+")
_MODELO = "Identificação do Modelo de Urna: "
_VERSAO = "Versão da aplicação: "
_UEFI = "Versão do UEFI: "
_MIDIA = "Mídia de votação gerada pelo computador (nome - tpm - instalação): "
_MIDIA_DT = "Data e hora da geração da mídia de votação: "
_CARGA_DT = "Data e hora da geração da mídia de carga: "
_SERIAL = "Serial da MV: "


def _seg(hhmmss: str) -> int:
    return int(hhmmss[0:2]) * 3600 + int(hhmmss[3:5]) * 60 + int(hhmmss[6:8])


def resumir_log(texto: str, dias: dict[int, str] = DIAS_ELEICAO) -> dict:
    """
    Percorre o log UMA vez e devolve indicadores do software e da operação da urna, no log todo e em cada
    dia de eleição (prefixos d1_ e d2_). O log do 2º turno é cumulativo: traz também o dia do 1º turno.
    """
    inv = {d: t for t, d in dias.items()}
    cont = {t: Counter() for t in dias}
    dur = {t: [] for t in dias}
    hab_em = {t: None for t in dias}
    urnas = {t: set() for t in dias}
    g = {}
    erros = Counter()
    assin_falha = n_erro = n_alerta = 0
    for linha in texto.split("\n"):
        p = linha.split("\t")
        if len(p) < 5:
            continue
        dh, nivel, uid, app, msg = p[0], p[1], p[2], p[3], p[4]
        t = inv.get(dh[:10])
        if nivel == "ERRO":
            n_erro += 1
            erros[RE_TPL.sub("#", msg)[:80]] += 1
            if t:
                cont[t]["erros"] += 1
        elif nivel == "ALERTA":
            n_alerta += 1
            if t:
                cont[t]["alertas"] += 1
        if "Verificação de assinatura" in msg and "[SUCESSO]" not in msg:
            assin_falha += 1
            erros["ASSINATURA: " + RE_TPL.sub("#", msg)[:70]] += 1
        # dados de identificação do software/mídia (primeira ocorrência)
        if app in ("SCUE", "GAP", "ATUE"):
            if "modelo" not in g and msg.startswith(_MODELO):
                g["modelo"] = msg[len(_MODELO):].strip()
            elif "versao" not in g and msg.startswith(_VERSAO):
                g["versao"] = msg[len(_VERSAO):].strip()
            elif "uefi" not in g and msg.startswith(_UEFI):
                g["uefi"] = msg[len(_UEFI):].strip()
            elif "midia" not in g and msg.startswith(_MIDIA):
                g["midia"] = msg[len(_MIDIA):].strip()
            elif "midia_dt" not in g and msg.startswith(_MIDIA_DT):
                g["midia_dt"] = msg[len(_MIDIA_DT):].strip()
            elif "carga_dt" not in g and msg.startswith(_CARGA_DT):
                g["carga_dt"] = msg[len(_CARGA_DT):].strip()
            elif "mv" not in g and msg.startswith(_SERIAL):
                g["mv"] = msg[len(_SERIAL):].strip()
        if t is None:
            continue
        c = cont[t]
        if app == "VOTA":
            urnas[t].add(uid)
            if msg == MSG_VOTO:
                c["votos"] += 1
                if hab_em[t] is not None:
                    dur[t].append(_seg(dh[11:19]) - hab_em[t])
                hab_em[t] = None
            elif msg == "Eleitor foi habilitado":
                c["habilitados"] += 1
                hab_em[t] = _seg(dh[11:19])
            elif msg == "Voto confirmado para [Presidente]":
                c["conf_pres"] += 1
            elif msg == "Tecla indevida pressionada":
                c["teclas_indevidas"] += 1
            elif msg.startswith("Eleitor corrigiu"):
                c["correcoes"] += 1
            elif msg.startswith("Solicita digital. Tentativa"):
                c["tent_digital"] += 1
            elif msg == MSG_MANUAL:
                c["manual"] += 1
            elif msg == "Solicita digital do mesário":
                c["mesario_digital"] += 1
            elif msg == "Identificador do eleitor digitado inválido":
                c["id_invalido"] += 1
            elif msg.startswith("Habilitação cancelada"):
                c["hab_cancelada"] += 1
            elif msg == "Eleitor foi suspenso pelo mesário":
                c["suspensos"] += 1
            elif msg == "Eleitor votou parcialmente e em seguida foi suspenso":
                c["votou_parcial"] += 1
            elif msg.startswith("Atribuido voto nulo por suspensão"):
                c["nulo_susp"] += 1
            elif msg.startswith("Mesário") and msg.endswith("habilitou o eleitor"):
                c["mesario_habilitou"] += 1
        elif app == "LOGD" and msg.startswith("Urna ligada em"):
            c["ligacoes"] += 1
        elif app == "INITJE" and msg.startswith("Urna desligada"):
            c["desligamentos"] += 1
    out = {"log_modelo": g.get("modelo"), "log_versao": (g.get("versao") or "").split(" - ")[0] or None,
           "log_uefi": g.get("uefi"), "log_mv": g.get("mv"), "log_midia_dt": g.get("midia_dt"),
           "log_carga_dt": g.get("carga_dt"), "log_assin_falha": assin_falha, "log_n_erro": n_erro,
           "log_n_alerta": n_alerta,
           "log_erros": " | ".join(f"{m} x{k}" for m, k in erros.most_common(3)) or None}
    if g.get("midia"):
        partes = [x.strip() for x in g["midia"].split(" - ")]
        out["log_midia_pc"] = partes[0]
        out["log_midia_tpm"] = partes[1] if len(partes) > 1 else None
    for t in dias:
        c, d = cont[t], np.asarray(dur[t], dtype=float)
        pre = f"d{t}_"
        for k in ("votos", "habilitados", "conf_pres", "teclas_indevidas", "correcoes", "tent_digital", "manual",
                  "mesario_digital", "id_invalido", "hab_cancelada", "suspensos", "votou_parcial", "nulo_susp",
                  "mesario_habilitou", "ligacoes", "desligamentos", "erros", "alertas"):
            out[pre + k] = int(c[k])
        out[pre + "n_urnas"] = len(urnas[t])
        d = d[(d >= 0) & (d < 3600)]
        out[pre + "dur_p10"] = float(np.percentile(d, 10)) if len(d) else np.nan
        out[pre + "dur_med"] = float(np.median(d)) if len(d) else np.nan
        out[pre + "dur_p90"] = float(np.percentile(d, 90)) if len(d) else np.nan
        out[pre + "dur_lt10"] = float((d < 10).mean()) if len(d) else np.nan
    return out
