# Changelog

Formato: [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/); versões em [SemVer](https://semver.org/lang/pt-BR/).

## [0.12.0] - 2026-10-31

### Adicionado
- Acompanhamento: além da classificação por espectro, avisa quando o ZTF (ALeRCE) ou o Rubin (Fink)
  detectam de novo um objeto acompanhado, pelos nomes internos que o TNS guarda (ZTF26… e IDs do LSST).
  A última detecção de cada um fica em `acompanhar.json` (`ultimas`); a primeira rodada só grava.

## [0.11.1] - 2026-10-31

### Corrigido
- Rubin: a ficha busca a última não-detecção na fotometria forçada do Fink (`/api/v1/fp`, S/R < 3 numa
  noite anterior, limite = 5 x o erro); sem noite anterior e com "fonte nova" (nada na referência), o
  rascunho usa a informação de arquivo ("Other") e deixa de ficar pendente.
- Gaia: se a TAP da ESA não responde, a ficha usa o espelho do GAVO (`gaia.dr3lite`); Gaia, NED e SkyBoT
  esperam 30 s e tentam 2 vezes (antes uma ficha chegava a 10 min).
- O resumo da ficha diz "não respondeu" quando um serviço falha (antes mostrava "nenhuma fonte").
- Filtros u/r/y do LSST (160/162/165) conferidos no formulário do TNS: saiu a pendência de "IDs inferidos".

## [0.11.0] - 2026-10-30

### Adicionado
- `--ficha OID`: checagens antes de reportar, todas fora do CDS (que derrubava SIMBAD e VizieR):
  TNS a 5", Gaia DR3 pela TAP da ESA (paralaxe > 5 sigma = estrela), SkyBoT na hora da detecção, galáxia
  hospedeira e redshift no NED (com magnitude absoluta) e a última não-detecção do ZTF na ALeRCE (a mais
  profunda da última noite). Recusa com uma detecção só e avisa quando o objeto está no núcleo da galáxia.
- `--enviar OID` (e `--sandbox`): envia o relatório pela API do TNS (`api/set/bulk-report`), lê a
  resposta (`api/get/bulk-report-reply`) e passa a acompanhar o AT novo; só envia depois que o usuário
  digita o OID. Com `"aprovar_por_dialogo": true` no `tns.json`, o `--avisar` abre uma janela do macOS
  ("Depois" / "Enviar ao TNS") para cada candidato novo do ZTF com a ficha limpa; sem clique, nada sai.

### Mudado
- O rascunho leva a última não-detecção (o TNS recusa sem ela) e a galáxia hospedeira nas observações;
  sem a não-detecção, aparece como pendência.

## [0.10.0] - 2026-10-25

### Adicionado
- Caçador de novas anãs (`--novas-anas`, e também em toda rodada com `--avisar`): candidatos CV/Nova dos
  classificadores de curva da ALeRCE (60 dias), fora do TNS (índice local, 3") e do VSX (um único
  cruzamento em lote no CDS X-Match, 5"); aprova quem tem >= 90% de detecções positivas, amplitude >= 2 mag,
  >= 4 detecções, duração <= 40 dias e g-r <= 1. Fonte Gaia DR3 brilhante a 1" marca "suspeito".
  Grava `novas_anas.json` e `novas_anas.html`, avisa uma vez por objeto (`novas_anas_estado.json`) e
  `--rascunho OID` também gera o rascunho do TNS com "likely dwarf nova outburst". Se o X-Match falhar,
  a rodada não avisa nada. O método achou 3 inéditas em 25/10/2026 (AT 2026agtu/agtv/agtw).

## [0.9.1] - 2026-10-24

### Corrigido
- Limite da ALeRCE (HTTP 429) em rodadas grandes descartava candidatos (452 de 2.777 numa busca de 30-120
  dias): agora respeita o `Retry-After` (ou espera 15/30/60 s), faz uma 2ª passada para quem falhou e usa
  4 consultas em paralelo em vez de 6.

## [0.9.0] - 2026-10-24

### Adicionado
- Busca local no TNS: o arquivo completo de objetos públicos (~211 mil, baixado no máximo uma vez por dia)
  é indexado por declinação e consultado em milissegundos (2.777 candidatos em 0,8 s, contra ~1,5 h pela
  API a uma busca a cada 6,5 s). A API só confirma o "não está" de quem tem nota de alarme, porque o
  arquivo é da meia-noite UTC.

## [0.8.0] - 2026-10-24

### Adicionado
- `--a-partir N`: pula os N dias mais recentes, para procurar no passado (ex.: `--dias 120 --a-partir 30`).
  Objeto antigo nunca reportado ainda pode ser reportado; o TNS registra a data da primeira detecção.
- Paginação da ALeRCE (antes vinham só os 500 primeiros).

## [0.7.1] - 2026-10-24

### Adicionado
- Novidades do dia em andamento: o arquivo diário do TNS só sai depois que o dia fecha, então cada rodada
  também busca na API (`public_timestamp`) as classificações desde a rodada anterior.
- Um objeto nunca é avisado duas vezes (nem pelo dia em andamento e depois pelo arquivo diário).

## [0.7.0] - 2026-10-24

### Adicionado
- Novidades do TNS sem email: arquivo diário de mudanças do TNS, resumo em `novidades.md` e aviso quando
  um candidato visto pelo CacaSN é classificado ou aparece um tipo raro.

## [0.6.0] - 2026-10-24

### Adicionado
- `--acompanhar NOME`: acompanha objetos do TNS e avisa quando forem classificados (lido da API, sem email).
- Cache do TNS (`tns_cache.json`) para objetos já reportados.

### Mudado
- Janela padrão de 21 dias (os dois objetos descobertos em 24/10/2026, AT 2026agsv e AT 2026agsw, tinham
  16–20 dias quando a nota ficou alta).
- No ZTF o TNS só é consultado de nota 15 para cima (no teste de 30 dias todos os alarmes estavam acima).
- Disjuntor para o VizieR fora do ar.

## [0.5.0] - 2026-10-23

### Adicionado
- `--rascunho OID`: relatório de descoberta (AT report) no formato de envio em lote do TNS 2.0, com
  fotometria e IDs de fonte/câmera/filtro do TNS. Só gera o arquivo; nunca envia.
- Curva de luz completa do Fink para os 30 melhores do Rubin e velocidade de subida (mag/dia por filtro)
  nos motivos.
- Curva com mais de 60 dias perde 5 pontos (os reportados ao TNS em julho tinham até 18 dias).

## [0.4.0] - 2026-10-23

### Adicionado
- Fonte Rubin (LSST) via o broker Fink (`--fonte ztf|rubin|ambas`), com nota própria medida contra o TNS
  (AUC 0.895 numa metade de teste), recortes, curva de luz e links para o portal do Fink.
- Fração do brilho que é nova (diferença contra referência) na nota do Rubin.
- Checagem no VSX (variáveis conhecidas) e, para o Rubin, no histórico do ZTF, para os candidatos do topo.
- Vigilância do fluxo do Rubin: avisa uma vez quando os alertas voltam (parados desde 14/07/2026).

### Corrigido
- O Fink responde 500 a datas em MJD: a busca usa ISO.

## [0.3.0] - 2026-10-23

### Adicionado
- Pacote `caca_sn` (`python -m caca_sn`, comando `cacasn`); `cacasn.py` continua como lançador.
- Log estruturado em JSON (structlog; cai no `logging` padrão se não estiver instalado) e Sentry opcional via `SENTRY_DSN`.
- Credenciais do TNS também por variáveis de ambiente (`TNS_BOT_ID`, `TNS_BOT_NAME`, `TNS_API_KEY`).
- CI (testes em 3.9 e 3.12, ruff, mypy, pip-audit, build do Docker), release por tag, Dependabot, `uv.lock`.
- Dockerfile, devcontainer, `.env.example`, CONTRIBUTING.

### Corrigido
- Objeto sem coordenada derrubava o relatório inteiro; agora é descartado.

## [0.2.0] - 2026-10-23

### Adicionado
- Classificador 2025 (beta) da ALeRCE e histórico de detecções na nota (AUC 0.96 contra o que foi reportado ao TNS).
- Alarme `--avisar` para candidato fora do TNS com nota ≥ 18.
- Testes offline com as APIs simuladas.

### Corrigido
- Travava sem salvar quando um candidato só tinha detecções negativas.
- "Subindo de brilho" comparava filtros diferentes.
- Gaia fora do ar era tratado como "não é estrela".
- `distnr = -999` (sem fonte) virava "no centro de uma fonte".
- Gravação de JSON atômica; novas tentativas com espera crescente; User-Agent identificado.

## [0.1.0] - 2026-10-22

### Adicionado
- Primeira versão: candidatos da ALeRCE, recortes, curva de brilho, checagem Gaia e TNS, `report.html`.
