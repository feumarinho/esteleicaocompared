"""
Estatística do projeto, dividida por tema. `from analise import ...` continua funcionando.

    abstencao  z da abstenção por seção (z ajustado, binomial, simples), funil
    horario    horário dos votos nos logs das urnas, fuso, sem digital / liberação manual
    turnos     comparação do desempenho dos candidatos entre os dois turnos
    fluxo      estimativa do fluxo de votos entre os turnos
    risco      os três critérios de risco e o cruzamento com o desempenho
"""
from .abstencao import *  # noqa: F401,F403
from .horario import *  # noqa: F401,F403
from .turnos import *  # noqa: F401,F403
from .fluxo import *  # noqa: F401,F403
from .fluxo import _nnls_gram  # noqa: F401  (usado em análises avulsas)
from .risco import *  # noqa: F401,F403
