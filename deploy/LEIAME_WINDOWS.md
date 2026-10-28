# Publicar o painel no servidor Windows (Caddy + NSSM)

```
navegador ──https──> Caddy (portas 80/443, já roda no NSSM)
                        │  deploy\Caddyfile.est: esteleicao.com -> 127.0.0.1:8503
                        ▼
                     painel Streamlit (serviço "esteleicao" no NSSM, só interno)
```

O Caddy só encaminha as requisições; ele não executa Python. Por isso o painel
roda como um serviço próprio no NSSM, ouvindo **só internamente** em
`127.0.0.1:8503` (nenhuma porta nova aberta para a internet).

O servidor **não precisa baixar nada do TSE**: ele usa os dados já processados
(`.parquet`) que você gerou no Mac.

## 1. No Mac: gerar o pacote

```bash
cd ~/Git/esteleicao
source .venv/bin/activate
python deploy/empacotar.py
```

Isso cria `pacote_servidor.zip` (código + `dados/*.parquet`, ~60 MB).

## 2. No servidor: copiar o pacote

Copie `pacote_servidor.zip` para `C:\git\` e, no PowerShell:

```powershell
Expand-Archive C:\git\pacote_servidor.zip -DestinationPath C:\git -Force
```

Isso atualiza `C:\git\esteleicao\` (código e pasta `dados`).

## 3. No servidor: instalar o serviço do painel

PowerShell **como Administrador**:

```powershell
cd C:\git\esteleicao
Get-ChildItem -Recurse | Unblock-File
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\deploy\instalar_servico_windows.ps1
```

O script cria o `.venv` com as bibliotecas (por isso não use o `python` direto:
ele não tem o pandas), registra o serviço `esteleicao` no NSSM (início
automático, reinício em caso de falha, log em `logs\servico.log`) e testa se o
painel respondeu em `http://localhost:8503`.

## 4. No servidor: ativar no Caddy

O Caddyfile principal precisa ter a linha (você já incluiu):

```
import C:/git/esteleicao/deploy/Caddyfile.est
```

Reinicie o serviço do Caddy no NSSM para ele ler a configuração:

```powershell
nssm restart NOME-DO-SERVICO-DO-CADDY
```

Requisitos do domínio (os mesmos do duad.live): o DNS de `esteleicao.com` e
`www.esteleicao.com` apontando para o IP do servidor. O Caddy emite o
certificado HTTPS sozinho; `http://` e `www.` redirecionam para
`https://esteleicao.com`.

## Atualizar depois

1. No Mac: `python deploy/empacotar.py`
2. No servidor: `Expand-Archive C:\git\pacote_servidor.zip -DestinationPath C:\git -Force`
3. No servidor: `nssm restart esteleicao`

## Comandos úteis

```powershell
nssm status esteleicao
nssm restart esteleicao
Get-Content C:\git\esteleicao\logs\servico.log -Tail 50
```

## Se for rodar os scripts de download no servidor

Use sempre o Python do `.venv` (criado no passo 3):

```powershell
C:\git\esteleicao\.venv\Scripts\python.exe coleta\baixar_dados.py
C:\git\esteleicao\.venv\Scripts\python.exe coleta\baixar_logs.py
```

## Problemas comuns

- **Página abre mas fica em "Connecting..."**: o painel não está rodando
  (`nssm status esteleicao`) ou o Caddy não foi reiniciado.
- **Erro de certificado**: o DNS do domínio ainda não aponta para o servidor.
- **Serviço para sozinho**: veja `logs\servico.log`. O painel precisa de
  ~1 GB de RAM, mais ~150–200 MB por visitante simultâneo.
