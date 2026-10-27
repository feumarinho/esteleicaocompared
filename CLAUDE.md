# CLAUDE.md — contexto do projeto esteleicao

Este arquivo resume tudo o que foi feito e decidido neste projeto, para que
qualquer sessão do Claude Code (no Mac ou no servidor Windows) continue o
trabalho sem precisar do histórico da conversa original.

**Idioma:** o usuário (Ricardo) conversa em português do Brasil. Responda em português.

## 1. Objetivo

Painel web (estilo BI) com dados abertos do TSE das **Eleições Gerais 2026
(1º turno, 04/10/2026)** para encontrar **seções eleitorais com comportamento
atípico** que possam (eventualmente) indicar irregularidade. Navegação
Brasil → UF → município → zona → seção.

O usuário quer focar em três padrões (aba "🚩 Sinalizadas"):

1. **Abstenção BAIXA** (abstenção alta não interessa).
2. **Voto após 17h significativo.**
3. **Liberação manual pelo mesário** de eleitores que **têm digital cadastrada**.

Postura combinada com o usuário: sinalização estatística **não é prova de
fraude**; a maioria dos casos tem explicação comum (fila, perfil do eleitorado,
cadastro biométrico, leitor com defeito). O painel público tem um aviso no topo
e uma seção "Como ler este painel". Manter esse tom.

## 2. Arquivos

| Arquivo | Função |
|---|---|
| `baixar_dados.py` | Baixa "Detalhe da apuração por seção eleitoral" (CDN do TSE) → `dados/secoes_<ano>_t<turno>.parquet` (aptos, comparecimento, abstenção por seção). |
| `baixar_logs.py` | Baixa os logs das urnas por UF e gera `dados/logs_<ano>_t<turno>_<UF>.parquet` (métricas por seção). |
| `download_tse.py` | Downloads resilientes: modo padrão baixa **só os logs** de dentro do zip remoto via HTTP Range (lê o diretório central do zip, 8 conexões, retomável, grava em `dados/logs_brutos_<ano>_<turno>t_<UF>.zip`); plano B `--completo` baixa o zip inteiro com retomada. |
| `logs_urna.py` | Parser do log da urna (`logd.dat`) e cálculo de métricas por seção. |
| `baixar_votos.py` | Baixa "Votação por seção eleitoral" (arquivo `votacao_secao_2026_BR.zip`, Presidente, 1º e 2º turno) → `dados/votos_<ano>_t<turno>.parquet` (colunas `v_<nº do candidato>`, `v_95` branco, `v_96` nulo) e `dados/candidatos_<ano>_t<turno>.json`. Votos batem 100% com o comparecimento oficial. |
| `gerar_resultado_risco.py` | Gera `resultados/risco_<ano>.parquet` (estático, vai no git): métricas dos 3 critérios de risco (logs do 1º turno) + desempenho dos candidatos no 2º turno por seção. Lido pela aba 🎯. |
| `analise.py` | Estatística: z da abstenção, z de proporções (sem digital, manual, após 17h), z do horário, sinais, correção de fuso. |
| `painel.py` | Painel Streamlit. |
| `gerar_dados_teste.py` | Gera dados sintéticos com anomalias plantadas (ano 1999) para testes. |
| `deploy/instalar_servico_windows.ps1` | Cria `.venv`, instala requirements, registra o serviço `esteleicao` no NSSM. |
| `deploy/Caddyfile.est` | Bloco do Caddy para `esteleicao.com` → `127.0.0.1:8503`. |
| `deploy/diagnosticar_caddy.ps1` | Diagnóstico do HTTPS no Caddy (acha serviço, valida config, reinicia, lê log, testa). |
| `deploy/empacotar.py` | Gera `pacote_servidor.zip` (código + `dados/*.parquet`) no Mac. |
| `deploy/LEIAME_WINDOWS.md` | Passo a passo de publicação no Windows. |

`dados/`, `logs/`, `.venv/`, `pacote_servidor.zip` estão no `.gitignore`.

## 3. Fontes de dados (TSE)

- Abstenção por seção: `https://cdn.tse.jus.br/estatistica/sead/odsele/detalhe_votacao_secao/detalhe_votacao_secao_2026.zip`
  (CSV `;`, latin-1; colunas usadas: NR_TURNO, SG_UF, CD_MUNICIPIO, NM_MUNICIPIO, NR_ZONA, NR_SECAO, CD_CARGO=1, QT_APTOS, QT_COMPARECIMENTO, QT_ABSTENCOES, NR_LOCAL_VOTACAO, NM_LOCAL_VOTACAO...).
- Logs das urnas ("Arquivos transmitidos para totalização"), um zip por UF:
  `https://cdn.tse.jus.br/estatistica/sead/eleicoes/eleicoes2026/arqurnatot/bu_imgbu_logjez_rdv_vscmr_2026_1t_<UF>.zip`
  (de centenas de MB a vários GB; CE ≈ 4,3 GB, BA ≈ 6,6 GB; ZIP64).
- O CDN do TSE tinha quedas de conexão (`Read timed out`); por isso o download por faixas com retomada.

### Formato dos logs em 2026 (diferente de 2022!)

- Nome: `o03220ac0101500020088-log.jez` = pleito 03220, UF `ac`, município 01015, zona 0002, seção 0088. Em 2022 era `....logjez`.
- `-log.jez` em 2026 é **ZIP comum** (em 2022 era 7z). Dentro: `logd.dat`, texto latin-1, TAB: `data hora | nível | id urna | app | mensagem | hash`.
- Mensagens usadas (app `VOTA`, só no dia da eleição = dia com mais votos):
  - urna pronta: `Aguardando digitação do título` (2022) / `Aguardando digitação do identificador do eleitor` (2026)
  - voto: `O voto do eleitor foi computado`
  - digital: `Tipo de habilitação do eleitor [biométrica]`
  - **sem cadastro**: `O eleitor não possui biometria` (2022) / em 2026 `Ano de nascimento digitado é igual ao do cadastro` **sem nenhuma tentativa de digital**
  - **liberação manual** (tinha digital, falhou 4 tentativas, mesário liberou): `Solicitação de dado pessoal do eleitor para habilitação manual`
- Validação com dados reais de 2026 (todas as UFs): 124,75 mi votos no log vs 124,93 mi comparecimento oficial; 99,6% das seções batem exatamente; 0 votos sem classificação. Brasil: sem digital 12,2% (sem cadastro 5,6%, manual 6,7%), votos após 17h 2,98%.

## 4. Métodos estatísticos (decisões)

- **z ajustado da abstenção** (padrão): `(taxa − esperada) / sqrt(p(1−p)/aptos + τ²)`; esperada = taxa do próprio município sem a seção (leave-one-out), UF se o município tem < 5 seções; τ² = variação natural entre seções, estimada por UF de forma robusta (mediana/MAD). Também existem z simples e z binomial (opções no painel).
- Mesmo método (`analise.z_proporcao`) para: % sem digital, % liberação manual (denominador = eleitores com digital cadastrada), % após 17h.
- **Horário**: tudo em horário de Brasília (8h–17h). A urna marca hora local. Fuso por seção = fuso oficial da UF (`FUSO_OFICIAL` em `logs_urna.py`: AC −2; AM, MT, MS, RO, RR −1; resto 0), trocado só se a abertura destoar > 45 min (casos reais: oeste do AM −2, Fernando de Noronha +1, leste do MT usa horário de Brasília = 0). Harmonizado pelo fuso mais comum do município. `analise.corrigir_fuso` reaplica a regra em parquets antigos usando os histogramas por hora (`h00..h23`, `s00..` sem digital, `m00..` manual), com resultado idêntico ao reprocessamento.
- Achado: Guaporema, Nova Olímpia e Tapira (PR, 40 seções) têm a curva de votos ~40 min adiantada → relógio das urnas adiantado; aparecem com "abertura atrasada" e % após 17h inflado. Não é indício de fraude.
- **Sinalizadas** (aba 🚩): critérios independentes, a seção mostra quantos cumpre (1, 2 ou 3, escolha na barra lateral):
  - abstenção baixa: z ≤ −limite (padrão 3) e ≥ 50 aptos;
  - voto após 17h: ≥ 15% dos votos após 17h e ≥ 10 votos; por padrão só conta se a hora média da seção for 30+ min mais tarde que as outras seções da mesma escola (escola inteira tarde = fila);
  - liberação manual: z_manual ≥ limite e ≥ 5 casos.
- **Cruzamento** (aba 🔀): score = min dos z dos critérios escolhidos na barra lateral.
- "sinais" por seção (texto): ≥10% após 17h; urna ociosa ≥20 min antes das 17h mas votos depois; maioria sem biometria após 17h; ritmo muito rápido após 17h; 1h+ mais tarde que a escola; sem digital/manual muito acima do município; 8+ liberações manuais seguidas; log ≠ comparecimento; urna substituída; abertura atrasada.

### Comparação 1º × 2º turno (aba 🔁, `analise.comparar_turnos`)

- Precisa de `secoes_2026_t1/t2` + `votos_2026_t1/t2` + `candidatos_*`. Os logs do 2º turno **não** são necessários (em 27/10/2026 ainda davam 404 no TSE).
- Por candidato presente nos dois turnos: votos e % dos votos válidos em cada turno; variação absoluta (`delta_votos`) e em p.p.
- **Desvio vs município**: onda do município (leave-one-out, UF se < 5 seções) medida em **logit** (evita estourar 100% em seções com 97%); `esperado_pp`, `desvio_pp`, `votos_vs_esperado` (desvio em votos) e `z_desvio` = desvio em logit ÷ escala **calibrada com os dados** (`_variancia_calibrada`: Var ≈ tau² + k×acaso, robusta/MAD, por UF). Calibrar é necessário porque os dois turnos têm os MESMOS eleitores: somar o acaso como independente deixava o z com desvio padrão 0,5 (escondia anomalias); calibrado, ≈ 1.
- Controle de abstenção: o desvio quase não se correlaciona com a variação da abstenção da própria seção (|corr| < 0,1), pois o esperado já usa os votos válidos reais do 2º turno. A tabela mostra `var_abst_pp`.
- Cortes sugeridos para "melhora muito grande": z ≥ 4 e |votos × esperado| ≥ 20 (padrões do painel; Lula ≈ 82 seções, Flávio ≈ 113).
- Atenção: no 1º turno há vários candidatos e no 2º dois; o valor bruto quase sempre sobe, por isso o que importa é o desvio contra o município.

### Fluxo de votos entre turnos (aba 🧭, `analise.preparar_fluxo` / `estimar_fluxos`)

- Regressão ecológica: em cada seção, o que foi para cada destino do 2º turno (Lula, Flávio, brancos+nulos, abstenção) é explicado pelo que cada origem do 1º turno tinha ali (Lula, Flávio, 3 maiores eliminados, demais, brancos+nulos, abstenção), com coeficientes ≥ 0 (NNLS em numpy, sem scipy, via X'X por município) e totais fechados por IPF. Peso 1/√aptos.
- Filtra por UF (sidebar); intervalo 5–95% por bootstrap de municípios (100 reamostragens, ~0,4 s). Município/zona caem para a UF (poucas seções).
- Achado nacional (27/10/2026): Flávio → Lula ≈ 0 (coef. sem restrição −0,04); os +10,4 mi do Lula viriam de brancos/nulos (~3,8 mi), ex-abstêmios (~3,4 mi) e eleitores dos eliminados (~3,6 mi). Cury → Lula 55%, Renan 33%, Caiado 30%.
- Limites: troca simétrica de lado é invisível; fluxos entre grupos que andam juntos no mapa (brancos/nulos × abstenção) são mal identificados; o intervalo cobre só o acaso amostral, não o erro do modelo.

### Risco do 1º turno × melhora no 2º (aba 🎯, `analise.marcar_criterios` / `resumo_cruzamento`)

- Cruza as seções marcadas pelos 3 critérios (calculados com os **logs do 1º turno**; o TSE ainda não publicou os do 2º) com o desempenho do candidato no 2º turno vs município (`z_desvio`, `votos × esperado`). Os critérios continuam ajustáveis na aba (mesma regra do painel original, função `marcar_criterios`).
- **Dados estáticos no git**: a aba lê `resultados/risco_<ano>.parquet` (+ `.json` com UFs e candidatos), gerado por `python gerar_resultado_risco.py` a partir de `dados/` (secoes t1/t2, votos t1/t2, logs t1). Em produção não baixa logs nem precisa de `dados/` para esta aba. Exterior (ZZ) fora; seções com < 30 votos válidos num dos turnos fora.
- Para regenerar: `python baixar_logs.py --turno 1` (≈ 50 GB baixados no total, ~10 MB/s; apagar `dados/logs_brutos_*` depois de cada UF), depois `python gerar_resultado_risco.py`, e commitar o parquet novo (cada versão pesa ~37 MB no histórico do git).
- Quando os logs do 2º turno saírem, dá para medir se as mesmas seções se repetem como de risco.

## 5. Painel: desempenho (importante para produção)

A base nacional tem ~500 mil seções × ~150 colunas (~300 MB em memória). Já otimizado:

- `st.cache_resource` (uma cópia compartilhada, não `cache_data`), com `assinatura` (nomes+datas dos arquivos) e `incluir_zz` no cache; base consolidada com `.copy()` (evita fragmentação) e tipos compactos (float32, inteiros menores, category).
- Nada de filtros que copiem a base inteira por visitante (`com_log` devolve a própria base se ≥ 90% das seções têm log; `filtrar` com subconjunto de colunas).
- Histogramas calculados no servidor (`histograma()`), dispersões com amostra de 15 mil pontos de fundo + todos os destacados.
- Medido com dados reais: ~0,9 GB com 1 visitante, ~1,4 GB com 5 simultâneos, ~2,9 GB com 10. Antes das otimizações, o servidor caía com 5.
- Correlação de Spearman feita com `rank().corr()` (scipy não está no requirements).

## 6. Publicação (servidor Windows)

- Servidor Windows, IP público **72.167.48.234**, repositório em **`C:\git\esteleicao`**.
- Já existem outros sites: o **Caddy** roda como serviço do **NSSM** com o Caddyfile principal em `C:\Git\veracibot\deploy\windows\Caddyfile` (importa blocos por site, ex.: `import C:/Git/duadlive/deploy/Caddyfile.duad` para o site estático duad.live).
- Arquitetura desejada pelo usuário: **porta padrão (80/443) pelo Caddy**, sem abrir porta nova:
  `navegador → Caddy (esteleicao.com, HTTPS automático) → 127.0.0.1:8503 (serviço NSSM "esteleicao", Streamlit)`.
  O Caddy não executa Python, então o painel precisa do próprio serviço NSSM (só interno).
- Serviço do painel: `deploy\instalar_servico_windows.ps1` (padrão `-Porta 8503 -Endereco 127.0.0.1`). Comando registrado:
  `.venv\Scripts\python.exe -m streamlit run painel.py --server.port 8503 --server.address 127.0.0.1 --server.headless true --server.fileWatcherType none --server.runOnSave false --browser.gatherUsageStats false --client.toolbarMode viewer`; log em `logs\servico.log`.
- **Não usar o `python` global** no servidor (não tem pandas): sempre `C:\git\esteleicao\.venv\Scripts\python.exe`.
- Dados: o servidor **não baixa nada do TSE**; usa os `.parquet` gerados no Mac (`deploy/empacotar.py` → `pacote_servidor.zip`, enviado ao servidor). A pasta `dados` não vai pelo git.
- WebSocket: o Streamlit 1.65 só aceita WebSocket se Origin == Host (ou `server.corsAllowedOrigins`). O Caddy repassa o Host original, então funciona sem configuração extra (testado: Origin do próprio domínio → 101; outro domínio → 403). Se um dia houver proxy que reescreva o Host, use `-Dominio https://esteleicao.com` no instalador.
- `Caddyfile.est` atual:
  ```
  esteleicao.com {
  	encode gzip
  	reverse_proxy 127.0.0.1:8503
  }
  www.esteleicao.com {
  	redir https://esteleicao.com{uri} permanent
  }
  ```
  Validado com `caddy validate`; testado com Caddy 2.8 + navegador na frente do Streamlit.

## 7. Estado atual e PRÓXIMO PASSO (onde paramos)

- ✅ Painel rodando no servidor em `http://localhost:8503` (confirmado pelo usuário).
- ❌ `https://esteleicao.com` dá **`ERR_SSL_PROTOCOL_ERROR`** no navegador = o Caddy aceita a conexão TLS mas não tem certificado para o domínio.
- Verificado de fora: DNS correto (`esteleicao.com` A → 72.167.48.234; `www` CNAME → esteleicao.com); o mesmo IP do duad.live; sem registro CAA; o SOA do DNS (serial 2026101101) indica que o registro foi criado/alterado **hoje (11/10/2026)**.
- Hipótese principal: o Caddy tentou emitir o certificado antes de o DNS propagar, falhou e entrou em espera crescente entre tentativas. Outras possibilidades: o `import` do `Caddyfile.est` não está no Caddyfile principal (ou está dentro de outro bloco), o caminho do import está errado, ou o Caddy não foi reiniciado.
- **A fazer no servidor:**
  1. Rodar `.\deploy\diagnosticar_caddy.ps1` (PowerShell como Administrador). Ele acha o serviço do Caddy no NSSM, confere o import, valida a configuração, reinicia o Caddy, mostra as linhas do log sobre `esteleicao.com` e testa `https://esteleicao.com` localmente.
  2. Ler o erro do ACME no log do Caddy (NXDOMAIN, timeout nas portas 80/443, rate limit...) e corrigir.
  3. Confirmar que `https://esteleicao.com` abre o painel e que o WebSocket conecta (sem "Connecting..." na página).
- Observação: o `Caddyfile.duad` original do usuário tinha `www.duad.live` redirecionando para `https://esteleicao.com` (provável engano de cópia); vale avisar o usuário.

## 8. Rotinas

- Atualizar dados/código no servidor: no Mac `python deploy/empacotar.py`; copiar o zip para `C:\git\`; `Expand-Archive C:\git\pacote_servidor.zip -DestinationPath C:\git -Force`; `nssm restart esteleicao`.
- 2º turno (25/10/2026): `python baixar_dados.py --turno 2` e `python baixar_logs.py --turno 2` no Mac, quando o TSE publicar.
- Testes sem internet: `python gerar_dados_teste.py`, depois `baixar_dados.py --ano 1999 --zip dados/teste_detalhe_votacao_secao.zip` e `baixar_logs.py --zip` para cada `dados/teste_arqurna_*.zip`.

## 9. Preferências e cuidados

- No Mac (zsh), não coloque comentários `#` na mesma linha de comandos que o usuário vai colar (o zsh interativo não os trata como comentário: deu erro no `pip install`).
- No Mac use `python3`/`.venv`; o usuário usa Python 3.14 no Mac.
- **Neste projeto (e só nele)** o usuário autorizou o Claude a fazer commits, push, merges e gerenciar o repositório. Isso não vale para outros projetos. Ainda assim, não apague nada nem reescreva histórico sem avisar.
- Explique em linguagem simples; o usuário não é estatístico.
