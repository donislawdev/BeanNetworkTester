<p align="center">
  <a href="README.md">English</a> | <a href="README.zh-Hans.md">简体中文</a> | <a href="README.ja.md">日本語</a> | <a href="README.de.md">Deutsch</a> | <a href="README.ko.md">한국어</a> | <a href="README.fr.md">Français</a> | <b>Português (Brasil)</b> | <a href="README.es.md">Español</a>
</p>

# Bean Network Tester 🫘 - simulador de condições ruins de rede (Windows) 
<p align="center">
  <b>Siga-me:</b>
  &nbsp
  <a href="https://discord.gg/bDTu8HX"><img src="https://cdn.simpleicons.org/discord/5865F2" alt="Discord" height="26" align="absmiddle"></a>
  &nbsp
  <a href="https://facebook.com/donislawdev"><img src="https://cdn.simpleicons.org/facebook/0866FF" alt="Facebook" height="26" align="absmiddle"></a>
  &nbsp
  <a href="https://x.com/donislawdev"><picture><source media="(prefers-color-scheme: dark)" srcset="https://cdn.simpleicons.org/x/FFFFFF"><img src="https://cdn.simpleicons.org/x/000000" alt="X (Twitter)" height="26" align="absmiddle"></picture></a>
  &nbsp
  <a href="https://bsky.app/profile/donislawdev.bsky.social"><img src="https://cdn.simpleicons.org/bluesky/0285FF" alt="Bluesky" height="26" align="absmiddle"></a>
  &nbsp
 <a href="https://store.steampowered.com/developer/DonislawDev"><picture><source media="(prefers-color-scheme: dark)" srcset="https://cdn.simpleicons.org/steam/FFFFFF"><img src="https://cdn.simpleicons.org/steam/000000" alt="Steam" height="26" align="absmiddle"></picture></a>
</p>

[![CI](https://github.com/donislawdev/BeanNetworkTester/actions/workflows/ci.yml/badge.svg)](https://github.com/donislawdev/BeanNetworkTester/actions/workflows/ci.yml)
[![Latest release](https://img.shields.io/github/v/release/donislawdev/BeanNetworkTester?sort=semver)](https://github.com/donislawdev/BeanNetworkTester/releases/latest)
[![Downloads](https://img.shields.io/github/downloads/donislawdev/BeanNetworkTester/total)](https://github.com/donislawdev/BeanNetworkTester/releases)
[![License: GPLv3](https://img.shields.io/badge/License-GPLv3-blue.svg)](LICENSE)
[![OpenSSF Scorecard](https://api.securityscorecards.dev/projects/github.com/donislawdev/BeanNetworkTester/badge)](https://scorecard.dev/viewer/?uri=github.com/donislawdev/BeanNetworkTester)
[![OpenSSF Best Practices](https://www.bestpractices.dev/projects/14154/badge)](https://www.bestpractices.dev/projects/14154)
![Platform: Windows](https://img.shields.io/badge/platform-Windows-0078D6)
![Platform: Linux (experimental)](https://img.shields.io/badge/platform-Linux%20%28experimental%29-FCC624)

O **Bean Network Tester** é uma ferramenta para testadores e desenvolvedores: veja como o seu
aplicativo se comporta em uma conexão ruim. Como o Clumsy ou o NetLimiter, ele permite degradar a
rede de propósito - adicionar ping, descartar pacotes, limitar a velocidade, derrubar conexões e
mais. Funciona interceptando o tráfego com o driver **[WinDivert](https://www.reqrypt.org/windivert.html)**
(via **[PyDivert](https://github.com/ffalcinelli/pydivert)**) e oferece tanto uma interface de
janela clara, com dicas (tooltips), quanto um modo de linha de comando para CI.

⭐ **Se ele economizou o seu tempo, deixe uma estrela.** É assim que o próximo testador que precisar
dele fica sabendo que existe.

**O que ele faz**

- **Adiciona lag e jitter** - atraso fixo ou aleatório, mais picos ocasionais.
- **Descarta, corrompe ou duplica pacotes** - a perda pode chegar em rajadas, do jeito que um link
  sem fio de verdade falha.
- **Limita a velocidade de download/upload** - restringe a um valor fixo de KB/s, com um buffer que
  adiciona atraso de fila antes de começar a descartar.
- **Derruba conexões** - resets de TCP, um link morto ou novas conexões que nunca se estabelecem.
- **Faz o link oscilar entre ligado e desligado** - quedas que vão e vêm.
- **Quebra o caminho, não só os pacotes** - um buraco negro de MTU e timeouts de inatividade no
  estilo NAT.
- **Bloqueia portas ou IPs** - um pequeno firewall embutido, além do modo LAN (sem internet) e do
  modo somente internet (sem rede local).
- **Mira em um aplicativo** - por nome de processo, PID, IP, porta ou uma família de endereços.
- **Perfis prontos e perfis salvos** - 56k modem, Cafe WiFi, Satellite, In-flight Wi-Fi e mais.
- **Executa cenários roteirizados** - etapas cronometradas que mudam a rede sozinhas.
- **Agenda o limite de velocidade** - uma linha do tempo repetida de taxas, sem precisar escrever
  um cenário.
- **Reproduzível por semente** - reexecute exatamente a mesma perda e o mesmo jitter aleatórios.
- **Repassa um bug** - um relatório com todas as configurações, os contadores e a linha de comando
  que repete a execução.
- **Acompanha ao vivo** - gráfico, contadores, uma tabela de conexões com busca e um registro de
  eventos.
- **Exporta para CSV** - estatísticas da sessão e um instantâneo da tabela de conexões.
- **Modo de linha de comando** - automatizável em CI, com códigos de saída e saída em JSON.
- **Sem telemetria, não envia nada por conta própria** - a ferramenta Ping só faz ping no
  endereço que você digita.

<p align="center">
  <img src="docs/demo.gif" alt="O Bean Network Tester adicionando lag e perda de pacotes a um ping ao vivo" width="820">
</p>

<p align="center">
  <a href="https://github.com/donislawdev/BeanNetworkTester"><img src="docs/star.gif" alt="Gostou? Dê uma estrela ao Bean Network Tester no GitHub" width="820"></a>
</p>

**Sumário**

- [Início rápido (3 passos)](#início-rápido-3-passos)
- [Idioma](#idioma)
- [Requisitos](#requisitos)
- [A janela](#a-janela)
- [Todas as opções explicadas](#todas-as-opções-explicadas)
- [Sintaxe de filtros (processo / IP / porta)](#sintaxe-de-filtros-processo--ip--porta)
- [Estatísticas (o que os contadores significam)](#estatísticas-o-que-os-contadores-significam)
- [Arquivo de configuração](#arquivo-de-configuração)
- [Modo de linha de comando (CLI)](#modo-de-linha-de-comando-cli)
- [Colunas de Connections](#colunas-de-connections)
- [Exportações em CSV](#exportações-em-csv)
- [Formato do arquivo de cenário](#formato-do-arquivo-de-cenário)
- [Receitas de CI/CD](#receitas-de-cicd)
- [Gerando um .exe](#gerando-um-exe)
- [Pegadinhas (leia antes de abrir um bug)](#pegadinhas-leia-antes-de-abrir-um-bug)
- [Testes](#testes)
- [Estrutura do projeto](#estrutura-do-projeto)
- [Como funciona (em resumo)](#como-funciona-em-resumo)
- [Observações e limitações](#observações-e-limitações)
- [Como contribuir](#como-contribuir)
- [Apoie o projeto](#apoie-o-projeto)
- [Autor](#autor)
- [Licença](#licença)
- [Componentes de terceiros](#componentes-de-terceiros)
- [Privacidade: sem telemetria](#privacidade-sem-telemetria)
- [Uma observação sobre o SmartScreen e o antivírus](#uma-observação-sobre-o-smartscreen-e-o-antivírus)

## Início rápido (3 passos)

1. Baixe o `BeanNetworkTester`: o **zip** roda sem instalar nada, e o **`.msi`** o instala para
   todos os usuários do computador, no `PATH` e no Menu Iniciar (exige permissões de
   administrador). Ou compile você mesmo: `pyinstaller --noconfirm BeanNetworkTester.spec`.
2. Execute o `BeanNetworkTester.exe` - o programa **pede permissões de administrador sozinho**
   (o WinDivert precisa delas). A partir do repositório: `python bean_network_tester.py`.
3. Escolha um perfil na lista "Profiles" (por exemplo, "3G network") e clique em **START**.

O **mesmo arquivo** executa o modo de texto: `BeanNetworkTester.exe --simulate --loss 10 --duration 5`.

No alto da janela, uma barra "Active: ..." resume o que você está fazendo agora
(por exemplo, *Active: +150 ms ping, 1% loss, download <= 384 KB/s*). Passe o mouse sobre qualquer
campo para ver uma dica (tooltip) explicando o que ele faz.

> Observação: selecionar um perfil apenas preenche os campos - a degradação só começa em **START**.
> Sem permissões de administrador, o driver WinDivert não carrega.

Procurando uma tarefa específica em vez do manual completo abaixo? Os
[guias no site](https://beannetworktester.donislawdev.com/pt-br/) explicam perda de pacotes,
latência, limites de velocidade, como mirar em um único aplicativo e como testar sem internet,
cada um com os números que vale a pena testar e o comando que faz isso. Outros dois mostram como
descobrir qual programa está usando uma porta e o que usar no lugar do `tc netem` ou do Network
Link Conditioner. Os guias estão escritos em 22 idiomas, do inglês e do polonês ao árabe e ao
vietnamita.

## Idioma

As traduções ficam em arquivos **`lang/<code>.json`** (incluídos: `lang/en.json`, `lang/pl.json` e
`lang/zh.json`, que é o chinês simplificado). Na inicialização, o app **varre o diretório `lang/`**
e detecta os idiomas disponíveis automaticamente. O idioma inicial segue a localidade do seu
sistema quando existe uma tradução correspondente e, caso contrário, recorre ao inglês. Um sistema
configurado em chinês tradicional também recebe inglês: o arquivo incluído é o simplificado, e os
dois são sistemas de escrita diferentes, e não duas grafias de um mesmo idioma. A lista
**Language** na janela Settings (a engrenagem no canto superior direito) troca o idioma a qualquer
momento - a interface é reconstruída no idioma escolhido, mantendo as suas configurações atuais.

**Tudo** na interface é traduzido: abas, rótulos, botões, dicas, cabeçalhos de coluna,
estatísticas, o painel da sessão, o registro de eventos, mensagens de log, caixas de diálogo e
mensagens de erro (exceções mostradas ao usuário). O código usa apenas **chaves** (por exemplo,
`app.tabs.statistics`) e o texto vem do arquivo de idioma. Quando uma chave não existe no idioma
escolhido, usa-se o inglês e, como último recurso, a própria chave. (A linha de comando - CLI - é
**sempre em inglês**, independentemente do idioma do sistema e da interface.)

**Adicionar um novo idioma** não exige nenhuma mudança no código: copie `lang/en.json` para, por
exemplo, `lang/de.json`, traduza os valores e preencha o cabeçalho
`"_meta": {"code": "de", "name": "Deutsch"}` - o idioma aparece na lista após reiniciar. Um arquivo
de idioma corrompido é ignorado (não derruba o app).

## Requisitos

- Windows 10/11 (64 bits), Python 3.10+ (com a opção tcl/tk)
- Permissões de administrador
- `pydivert` (captura de tráfego), `psutil` (um recurso alternativo, veja abaixo)

A instalação a partir do código-fonte funciona no Python 3.10 e mais novos. A CI testa e compila
**somente na 3.14** - essa é a versão com a qual o `.exe` publicado é empacotado, então as mais
antigas são suportadas, mas não são comprovadas de novo a cada commit.

No Windows, o Python 3.10 a 3.12 mede o tempo em passos de 15,6 ms. Cada pacote é cronometrado por
esse relógio, então latência, jitter e limites de velocidade menores que um passo saem em passos
inteiros, e o `--doctor` avisa sobre isso. O Python 3.13 e mais novos, e o `.exe`, medem em
microssegundos.

O `psutil` é instalado junto com a ferramenta, mas não é ele que faz o direcionamento por processo
funcionar no Windows. Lá, a tabela de sockets e os nomes dos processos vêm direto do sistema
operacional, e o direcionamento continua funcionando mesmo com o `psutil` removido por completo
(medido: 310 portas mapeadas, 37 de 37 nomes resolvidos). Ele é o recurso alternativo para todo o
resto, e é assim que os testes do motor rodam no Linux, sem driver nenhum.

## A janela

A janela **se adapta à tela e à escala do sistema (DPI)**. O tamanho inicial é calculado a partir
da resolução (cabe em 1366x768 e cresce em Full HD / 2K / 4K), e todas as dimensões - larguras de
coluna, alturas de linha das tabelas, margens do gráfico, quebra de texto - escalam com a fonte. O
programa se declara **compatível com DPI Per-Monitor-V2**, então mover a janela para um segundo
monitor com outra escala não deixa a interface borrada.

O tamanho e a posição da janela, a aba selecionada, o idioma, as seções recolhidas, a divisão entre
o log e as abas e a ordem de classificação das tabelas ficam salvos em
`bean_network_tester_ui.json` (ao lado dos perfis). A geometria salva é validada antes do uso - uma
janela deixada em um segundo monitor abre lá de novo, e se esse monitor não existir mais, ela volta
para o centro da tela atual.

- **Control** - todas as configurações de degradação, agrupadas em **seções recolhíveis** (o estado
  recolhido é lembrado). Em uma janela larga, as seções se organizam **em duas colunas** (em vez de
  uma coluna estreita e uma metade direita vazia), então há bem menos rolagem. A aba inteira rola,
  inclusive com a **roda do mouse**.
- **Statistics** - três subabas, para que nada fique cortado em telas pequenas:
  - **Live** - contadores (pacotes, perdidos, corrompidos, derrubados...) e um gráfico de vazão. A
    grade de contadores escolhe o número de colunas para caber na largura da janela. Um botão
    "Export CSV".
  - **Session** - semente, duração, dados usados, picos + os botões "Mark bug", "Save repro
    report" e "Copy CLI command".
  - **Events** - o registro de eventos (START/STOP/CHANGE/SCENARIO/BUG/RESET).
- **Connections** - uma visão de com quais IP:porta o sistema testado conversa. Cada coluna está
  documentada em [Colunas de Connections](#colunas-de-connections) mais abaixo, e cada uma também
  tem uma dica no cabeçalho. O tráfego que não tem porta nenhuma - o ping (ICMP) - também é listado,
  uma linha por endereço, com as células de porta vazias.
  - **"down"/"up"/"total" são o que o aplicativo realmente recebeu**, a mesma quantidade que o
    painel da sessão chama de "Downloaded (MB)". **"down seen"/"up seen" são o que a ferramenta
    capturou** antes de degradar qualquer coisa. Sem nada configurado, os dois são iguais. No
    momento em que você adiciona perda ou um limite de velocidade, eles se separam, e **a diferença
    entre os dois é o estrago naquela conexão**. Passe o mouse sobre qualquer um deles para ver a
    frase completa. (Antes dessa separação havia um único par, com os bytes capturados sob títulos
    que significavam entregues: uma linha podia mostrar 5 MB recebidos enquanto o aplicativo havia
    recebido 0,4 MB.) Há ainda uma caixa de busca (com debounce, para não sobrecarregar a tabela a
    cada tecla digitada),
  cabeçalhos que ordenam ao clicar, **"Freeze"** (as linhas param de fugir de baixo do cursor) e um
  **menu de clique direito**: copiar linha / IP, **"Target this process"**, **"Limit to this
  IP:port"** - preenche os campos de filtro com um clique. **"Reset this connection"** derruba
  aquela conexão na hora, com ou sem uma sessão em andamento: o programa que a usa recebe um erro,
  e a outra ponta recebe um reset de TCP. Durante uma sessão, esse reset passa pelas degradações
  como qualquer outro pacote, então uma perda alta pode descartá-lo no caminho. Funciona apenas
  para TCP sobre IPv4 - o Windows não tem como resetar uma conexão IPv6 - então a entrada aparece
  esmaecida nas outras linhas, e ela exige permissões de administrador.
  A tabela é **virtualizada**: desenha só as linhas que estão de fato na tela, então a rolagem é
  instantânea, seja com 400 linhas ou com algumas centenas de milhares. O antigo limite fixo de 400
  linhas acabou - quantas mostrar é definido no campo **"Row limit"** (seção *Tables*, 0 = sem
  limite, padrão 50 000).
- **Tools** - pequenos auxiliares para dúvidas que surgem antes ou durante um teste, uma subaba para
  cada. Só o **Ping** envia algo pela rede nesta aba: solicitações de eco para o endereço que você
  digita, de Start a Stop. Hoje:
  - **Sockets** - todos os sockets TCP e UDP deste computador, como o `netstat -ano`, e sem
    precisar de sessão: o que está escutando, o que está conectado, o estado (LISTEN,
    ESTABLISHED, TIME_WAIT...) e o programa dono. Use para ver em qual porta o seu aplicativo
    escuta antes de degradá-lo, ou qual programa está usando uma porta. A tabela é lida quando
    você abre a aba e quando pressiona **Refresh**. Pesquise nela do jeito que pesquisa na tabela
    de conexões (`lport:8080`, `state:listen`, `proc:chrome`) e clique com o botão direito em uma
    linha para direcionar ao programa dela, deixá-lo em paz, ou limitar ao endereço remoto dela ou
    bloqueá-lo. Os nomes dos programas aparecem sem permissões de administrador.
  - **Port check** - o seu programa pode usar uma porta? Digite uma porta, uma lista ou uma faixa,
    do jeito que você digita portas na página Control (`8080`, `80, 443`, `9000-9100`, até 1000 por
    vez) e pressione **Check** (ou Enter). Cada porta é verificada para TCP e UDP, em IPv4 e IPv6,
    e marcada como **Free**, **In use** (com o programa que a usa e o respectivo PID) ou
    **Reserved by Windows** - uma faixa que o Windows reservou, o motivo mais comum de um servidor
    não subir em uma porta que parece livre. As faixas valem por protocolo, então uma porta pode
    estar livre para UDP e não para TCP. Para cada porta, a ferramenta pergunta ao sistema no
    endereço de loopback do próprio computador e devolve a porta na hora. Quem usa uma porta vem da
    mesma tabela do **Sockets**. Clique com o botão direito em uma linha para direcionar ao programa
    que usa a porta ou deixá-lo em paz.
  - **Filter tester** - escolha um campo da página Control (processo alvo, IP ou porta de destino,
    IP ou porta bloqueados), digite uma expressão e um valor, e veja na hora se eles combinam.
    Também mostra qual parte da expressão selecionou o valor, qual parte com `!` o excluiu e como o
    programa interpreta o que você digitou. Um valor que não é um endereço, uma porta nem um PID é
    reportado como tal, e não como "não combina". **"Use in the Control field"** coloca a expressão
    nesse campo, substituindo o que estiver lá. O que você digita permanece até fechar o programa,
    mesmo que você troque o idioma.
  - **Adapters** - todos os adaptadores de rede deste computador e as configurações de que um teste
    depende, do tipo que o `ipconfig /all` imprime (somente Windows). O adaptador por onde sai o seu
    tráfego de internet fica no topo,
    depois os que estão ativos. Escolha um para ver seus endereços com os prefixos, o gateway, os
    servidores DNS, o DHCP, o endereço MAC, o MTU e a velocidade do link. Um aviso alerta quando
    outro dispositivo usa o mesmo endereço. A lista é lida quando você abre a aba e quando pressiona
    **Refresh**. Clique com o botão direito em um gateway ou servidor DNS para colocar o endereço
    dele no campo de IP de destino da página Control (a porta lá permanece). A primeira linha,
    **Proxy**, mostra se os programas passam por um proxy: as configurações desta conta (detecção
    automática, um script de configuração, um servidor proxy e o que passa ao largo dele), o proxy
    que os serviços do Windows usam (WinHTTP) e as variáveis `HTTP_PROXY`, `HTTPS_PROXY`,
    `ALL_PROXY` e `NO_PROXY`. Um programa que usa um proxy se conecta ao proxy, e não ao seu alvo -
    clique com o botão direito no servidor proxy para limitar as degradações ao endereço dele.
    Um proxy informado por nome não é resolvido, e senhas em um endereço ficam ocultas.
    **"Copy report"** copia todos os adaptadores e as configurações de proxy em inglês - o texto
    contém os endereços e os endereços MAC deste computador.
  - **Diagnostics** - por que o START não funciona, sem precisar de console. Executa as mesmas
    verificações do `--doctor` (permissões de administrador, o driver WinDivert, sobras na pasta
    temporária...) e marca cada uma como OK, Warning ou Problem. **"Clean up the driver"**
    descarrega um driver WinDivert que ficou carregado (somente com permissões de administrador,
    nunca durante uma sessão). **"Copy environment report"** copia a linha do `--version` e a saída
    do `--doctor`, pronto para colar em um relatório de bug. O relatório inclui caminhos de pastas,
    e um caminho pode conter o seu nome de usuário do Windows. Marque **"Add network adapters"** ou
    **"Add proxy settings"** para incluir também os adaptadores ou o proxy no relatório - ambos
    ficam desligados até você marcá-los, porque os endereços dizem em qual rede este computador
    está.
- Na parte de baixo: **START/STOP**, **Apply changes** e **Load/Save file**, com o log abaixo.
  Essa barra fica ancorada na borda inferior - nenhuma aba pode cobri-la.

### Quando as mudanças entram em vigor

**Nada se aplica sozinho.** Um perfil pronto, um perfil salvo, o modo LAN e um arquivo de
configuração carregado **apenas preenchem o formulário**. Eles só chegam a uma sessão em andamento
por meio de **"Apply changes"** - o botão fica **destacado** quando o formulário difere do que o
motor está de fato fazendo. A barra abaixo do título diz o que você está vendo:

| Prefixo | Significado |
|---|---|
| `Preview:` | o app está parado - isto descreve o que vai acontecer depois do START |
| `Active:` | isto é exatamente o que está aplicado ao tráfego agora |
| `Unapplied changes:` | o formulário foi alterado - clique em "Apply changes" |

Enquanto uma sessão roda, **dois elementos ficam travados** (eles destravam no STOP): o **filtro de
tráfego** (aplicado só no START) e o **seletor de idioma** (trocar o idioma reconstrói toda a
interface). O botão STOP é vermelho - não dá para confundi-lo com o START.

Um campo que outra configuração assumiu fica **esmaecido junto com o seu rótulo**, com uma nota
dizendo qual configuração o assumiu - "Download"/"Upload" fazem isso quando um Schedule está
definido, porque a vazão passa a vir das etapas do agendamento. Dá para ver num relance o que está
realmente em vigor.

### Atalhos de teclado

| Atalho | Ação |
|---|---|
| `F5` | START / STOP |
| `Ctrl+Enter` | Apply changes |
| `Ctrl+S` / `Ctrl+O` | Salvar / carregar o arquivo de configuração |
| `Ctrl+L` | Limpar o log |
| `Ctrl+F` | Busca: a busca de campos em Control, a busca na tabela em Connections, a busca de sockets em Tools > Sockets |
| `Up` / `Down`, `Page Up` / `Page Down`, `Home` / `End` | Em uma tabela: move a seleção. Com `Shift`, seleciona um intervalo, que pode passar de uma tela. `Ctrl+C` copia as linhas selecionadas e `Shift+F10` abre o menu de clique direito |
| `Enter` / `Tab` / `Escape` | Em uma janela de pergunta ou de mensagem: `Enter` aciona o botão destacado (o padrão quando a janela abre), `Tab` passa para o próximo botão, `Escape` fecha a janela, respondendo "No" ou "Cancel" onde há uma pergunta |

**Encontrando uma configuração.** A caixa no alto da página Control busca as configurações pelo nome -
digite parte do nome de um campo ou de uma seção, ou a flag da linha de comando, como `--loss`. Cada
resultado é destacado e aquele em que você está fica preenchido, então o contador `1 / 4` sempre
aponta para algo que você consegue ver. `Enter` vai para o próximo resultado, `Shift+Enter` volta e
`Escape` limpa a caixa. Uma seção recolhida abre enquanto a busca durar e volta a recolher depois. Os
acentos são opcionais. Se o que você procura for uma das configurações que ficam na janela Settings,
a busca avisa.

### Validação de campos

Os campos numéricos são verificados **ao vivo, junto com a faixa** (por exemplo, perda 0-100%,
latência 0-600000 ms): um campo inválido fica vermelho e o motivo aparece abaixo da seção. O mesmo
vale para as expressões de filtro. A mesma faixa vale na CLI - `--loss 250` agora é um erro, e não
um ajuste silencioso para 100%.

## Todas as opções explicadas

**Traffic to modify** - qual tráfego capturar, afinal. Opções: os dois sentidos (TCP+UDP+ICMP),
somente saída, somente entrada, somente TCP, somente UDP, somente ICMP (ping), somente loopback
(127.0.0.1/::1 - para testar a comunicação entre processos locais). Todos os filtros cobrem **IPv4
e IPv6**. (Se o ping "não reage", quase sempre é porque o filtro escolhido não inclui o ICMP.)

**O tráfego de loopback conta como upload.** O Windows entrega os dois sentidos de uma conversa
entre dois programas deste computador como saída, seja qual for o filtro escolhido. Para esse
tráfego, **Download**, a coluna de download do agendamento e o **NAT timeout** não têm efeito, e os
valores principais também não, quando o upload tem valores separados. O limite de **Upload** vale
para os dois sentidos juntos, e um processo alvo é afetado somente no que envia. Com o filtro de
loopback, o programa avisa isso quando essas configurações são aplicadas.

> **Observação:** não existem perfis por porta ("DNS/HTTP/HTTPS only") - para restringir por porta,
> use o campo **Port** em "Target destination", que entende listas, faixas e exclusões
> (`80,443,8000-8100`, `!53`). Dois lugares decidindo sobre portas, com semânticas diferentes, só
> confundiriam.

O **Traffic filter** é aplicado na partida, então durante a execução fica **travado** - para
mudá-lo, pare (STOP), escolha outro e inicie de novo (START).

**LAN mode** - uma caixa de seleção "LAN mode (local network only, no internet)". Ela rejeita o
tráfego de/para endereços públicos (da internet) e deixa passar a rede local: 10.0.0.0/8,
172.16-31.x, 192.168.x, loopback, link-local e CGNAT. Simula "a LAN funciona, a internet caiu" - um
teste de como o aplicativo se comporta sem acesso à internet (por exemplo, sem gateway/WAN, um
portal cativo).

**Internet only** - o espelho dele, uma caixa de seleção "Internet only (no local network)" na
mesma seção. Ela descarta o tráfego de/para esses mesmos endereços locais e deixa a internet
funcionando, para que você possa testar um aplicativo que conversa com um servidor de intranet, um
NAS ou uma impressora enquanto a WAN está boa. Há duas coisas que ela não faz, e as duas importam:

- **O loopback continua funcionando.** 127.x e `::1` passam nos dois casos, então um servidor de
  desenvolvimento local, um banco de dados na sua própria máquina e qualquer coisa que use o
  loopback para falar consigo mesma ficam intactos. Isso é de propósito: a sua própria máquina
  falando consigo mesma não é "a rede local".
- **O roteador está na rede local.** Se o seu PC pergunta ao roteador pelo DNS, a resolução de
  nomes para de funcionar junto com ele, e a internet parece quebrada mesmo com o tráfego de
  internet sendo liberado. Use um resolvedor DNS público durante este teste se isso atrapalhar.

As duas caixas podem estar ligadas ao mesmo tempo. Isso é permitido e corta tudo, menos o loopback -
o programa avisa no log quando você aplica, e cada um dos dois contadores informa a sua própria
metade.

**Target process** - restringe o efeito a aplicativos escolhidos: nome do processo (por exemplo,
`chrome.exe`), PID, uma lista separada por vírgulas, faixa de PIDs, curinga ou expressão regular -
veja [Sintaxe de filtros](#sintaxe-de-filtros-processo--ip--porta). O resto do tráfego da máquina
fica intacto. Campo vazio = todo o tráfego.

**Speed limit** - vazão máxima separadamente para download (entrada) e upload (saída), em KB/s.
0 = sem limite. O ping são pacotes pequenos, então um limite de velocidade quase não o altera - para
testar o limite, use o download de um arquivo. Um valor positivo sempre limita alguma coisa: um
limite extremamente pequeno (abaixo de 1 B/s) é elevado a 1 B/s e não vira silenciosamente "sem
limite".

**Speed unit (janela Settings)** - se a página Statistics, o gráfico e o indicador ao lado desses
dois campos mostram a vazão em `KB/s`, `Mbit/s` ou `MB/s`. Isso muda o que você LÊ, nunca o que você
digita: os limites em si continuam em KB/s, porque esse é o número que um arquivo de configuração
salvo, o agendamento de vazão, os cenários incluídos, `--down`/`--up` e a saída NDJSON carregam.
Escolha uma unidade e um `(= 8.39 Mbit/s)` em cinza aparece ao lado do campo, para que você digite o
número que a ferramenta quer enquanto lê o número com que o seu link é vendido.

> **O `K` aqui é 1024, e um megabit é um milhão decimal** - as duas convenções não se anulam,
> então 1024 KB/s são **8,39 Mbit/s**, e não 8. Essa é a conversão honesta, e não um erro de
> arredondamento: um byte tem 8 bits, `1024 x 1024 x 8 = 8 388 608` bits por segundo, e megabit
> significa 10^6 bits em todo lugar onde se vende um link. Divida por 8,39, e não por 8, quando
> quiser que um limite corresponda a uma velocidade anunciada.

**Buffer** - a capacidade do buffer do link para um limite de velocidade, em milissegundos
(0 = buffer ilimitado). Define quanto atraso de fila pode se acumular em um link com velocidade
limitada antes que ele comece a descartar o excesso (bufferbloat). Sem esse buffer, o token bucket
poderia "fugir" dezenas de segundos para o futuro: os pacotes levavam atrasos extremos, e aumentar o
limite no meio da sessão (por exemplo, uma etapa de agendamento "o link se recupera") não tinha
efeito, porque a fila acumulada engolia todas as etapas mais rápidas. Com um buffer de `N` ms, o
atraso fica limitado a ~`N` ms, o excesso vai como "Rate-limit drop" (um contador separado, não
"Loss" nem "Buffer overflow"), e depois de aumentar o limite a vazão se recupera em ~`N` ms. Padrão
1000 ms. Ativo somente com um limite de download/upload ou um agendamento definido. O tempo no
buffer se soma à *Latency*, como em um link real: com 200 ms de latência e um buffer cheio de 150 ms,
um pacote chega depois de cerca de 350 ms.

**Delay (ping)** - *Latency*: quantos ms adicionar a cada pacote. *Jitter*: variação aleatória do
atraso (+/- ms), que faz o ping oscilar e reordena pacotes. Três coisas que vale saber:

(0) **O ping sobe cerca do dobro da latência que você define.** O atraso é adicionado a cada
pacote e, com o filtro padrão de tráfego nos dois sentidos, isso vale tanto para a requisição quanto
para a resposta - então `--latency 100` aparece como cerca de +200 ms de ping (medido:
`--latency 200` levou um ping de loopback de menos de 1 ms para ~408 ms). Escolha a metade do ping
que você quer. O jitter **não** dobra do mesmo jeito: cada pacote sorteia o seu próprio valor, então
a oscilação cresce cerca de 1,4x, chegando a 2x só nos extremos. Os perfis prontos incluídos são
calibrados assim - o `Satellite (geostationary)` carrega 340 ms e entrega o ping de ~680 ms que um
link geoestacionário real tem.

(1) o jitter adiciona um atraso aleatório independente a cada pacote, então os pacotes podem se
ultrapassar na fila - o jitter **reordena pacotes** por natureza (uma rede real faz o mesmo).
(2) As oscilações negativas são cortadas em zero, então quando o jitter é **maior que a latência**, o
atraso médio adicionado fica acima da própria latência (por exemplo, latência 0 e jitter 50 ms dão
cerca de metade dos pacotes sem atraso e uma média de ~12 ms, e não 0). Quando a latência é maior
que o jitter, o efeito é desprezível.

O *Latency spike* fica na mesma seção, porque um pico também é latência - uma ocasional e grande.
Com a probabilidade dada, ele acrescenta um atraso extra (ms) a um **único pacote**, que é como o
"lag" momentâneo realmente chega. A chance é por pacote e vale **em cada sentido**, então uma ida e
volta sofre isso cerca do dobro de vezes que o número sugere.

**Testando a entrega fora de ordem** - é para isso que serve o par do pico, e é por isso que a seção
se chama "Latency (ping) and packet order". Um pacote com pico chega depois de pacotes que foram
enviados depois dele, então *Spike chance* e *Spike size* reordenam o tráfego **sem** espalhar o
atraso de todos os outros pacotes como o jitter faz - o que importa quando o que está sob teste é um
protocolo UDP que precisa sobreviver sozinho à reordenação: um jogo, o QUIC, telemetria, voz.
Defina um tamanho de pico maior que o intervalo entre os seus pacotes, ou nada vai ultrapassar nada.

Se isso realmente aconteceu é uma pergunta separada de se foi configurado, então a ferramenta conta:
**Reordered** na página Statistics (e `packets_reordered` no CSV de estatísticas). 0 com um pico
definido significa que o seu tráfego foi esparso demais para algum pacote ultrapassar outro - e não
que a configuração foi ignorada. A contagem é por sentido, então duas conexões movimentadas podem se
ultrapassar sem que nenhuma das pontas veja algo fora de ordem.

**Impairments** - *Loss*: porcentagem de pacotes que somem sem deixar rastro (5% já é uma rede
claramente falhando). *Corruption*: porcentagem de pacotes com um bit de dados invertido - afeta
**somente pacotes que carregam dados**. Pacotes sem dados (por exemplo, ACK puro, SYN) não têm o que
inverter, então passam intactos e **não são contados como corrompidos**. *Duplication*: porcentagem
de pacotes enviados duas vezes.

**Losses in a row (burst)** - links reais raramente perdem pacotes um de cada vez. Um forno de
micro-ondas, um elevador ou a troca entre transmissores tira a conexão do ar por um instante, e tudo
o que foi enviado nesse instante se perde. Este campo diz quantos pacotes se perdem em sequência
**em média**, enquanto a *Loss* continua decidindo quanto se perde no total. Importa mais do que
parece: 5% espalhados é algo que a maioria das conexões absorve, enquanto os mesmos 5% em rajadas de
vinte travam uma transferência, derrubam uma conexão ativa e mandam o aplicativo para o seu caminho
de reconexão. Defina 0 para espalhar a perda de modo uniforme, que é o que a ferramenta fazia antes
de esta configuração existir.

Dois limites que vale conhecer, e o log informa os dois quando você aplica as configurações. Uma
perda muito alta não consegue chegar em rajadas muito curtas, porque rajadas tão curtas deixam
espaço de menos entre elas, então a execução informa o que vai realmente entregar. E um comprimento
de rajada grande afasta as rajadas umas das outras, então uma sessão curta pode nem ver uma. Cada
sentido tem as suas próprias rajadas, então uma rajada de vinte significa vinte seguidos naquele
sentido, e com Asymmetry ligada o log informa os dois limites também para o upload. Com 100% de
perda, todo pacote se perde, então o comprimento da rajada não muda nada.

**Oscilação do link (link flapping)** - perda total cíclica de tráfego: a cada *Period* segundos, o
link fica morto pela porcentagem do tempo informada. Simula uma conexão que pisca. Isto **não** é a
mesma coisa que perdas em sequência: a oscilação é um ciclo fixo que dá para prever, e as rajadas
acima são aleatórias e curtas, no meio de um tráfego que de resto é normal.

**Advanced (NAT / connections):**
- *Target destination (IP/port)* - degrada apenas o tráfego de/para servidores escolhidos. Os dois
  campos aceitam listas, faixas, CIDR, curingas, comparações, exclusões e expressões regulares -
  veja [Sintaxe de filtros](#sintaxe-de-filtros-processo--ip--porta). Por exemplo, IP
  `10.0.0.1-10.0.0.50,!10.0.0.7`, porta `80,443,8000-8100`. Vazio = qualquer um.
- *TCP SYN drop (%)* - porcentagem de pacotes de abertura de conexão descartados. Simula uma conexão
  que não se estabelece (teste de novas tentativas) - útil para testes de quem está atrás de um NAT.
- *Max size (MTU)* - descarta pacotes maiores que N bytes. Reproduz um "buraco negro de MTU" de
  túneis/VPN/atrás de NAT (os pequenos passam, os grandes somem). 0 = desativado.
- *NAT timeout* - se uma conexão fica em silêncio por mais de N segundos, o próximo pacote de entrada
  é descartado (o mapeamento "desaparece"). Um teste de keep-alive. 0 = desativado.
- *TCP tear-down (RST)* - porcentagem de conexões derrubadas abruptamente com um pacote RST. Força
  reconexões. **Somente TCP** (RST é um conceito do TCP, o UDP não pode ser "derrubado" - use perda
  ou oscilação do link). O botão **Tear down TCP now** reseta todas as conexões TCP ativas por ~3 s.
- *Schedule* - vazão que muda ao longo do tempo: `time:download:upload` em KB/s, separados por
  vírgulas. Por exemplo, `2:100:0, 2:500:0` = 2 s a 100 KB/s, depois 2 s a 500, em laço. Quando o
  agendamento não está vazio, ele **sobrepõe** os campos fixos "Download/Upload" - a interface os
  esmaece e avisa isso explicitamente. O tempo de uma etapa é maior que 0 e no máximo 86400 s, e cada
  velocidade vai de 0 (sem limite) a 10000000 KB/s, como nos campos fixos. Uma etapa fora disso é
  recusada e nomeada.

**Session:**
- *Duration (s)* - depois desse número de segundos, o programa **para sozinho** (exatamente como se
  você clicasse em STOP): a degradação desaparece, o driver é liberado. `0` = roda até o STOP (o
  comportamento anterior, que é o padrão). O equivalente na CLI é `--duration`. Como o filtro de
  tráfego, ele é considerado **somente no START** ("Apply changes" não mexe nele). O valor é salvo no
  arquivo de configuração e no comando de reprodução.

**Repetibilidade e cenário:**
- *Seed* - defina qualquer número para que toda execução sorteie do mesmo jeito (um bug passa a ser
  reproduzível). Vazio = diferente a cada vez. Considerado **somente no START**, então fica travado
  enquanto uma sessão roda.
- *Scenario* - um arquivo JSON que muda configurações em tempo real (por exemplo, depois de 10 s
  adiciona ping, depois de 20 s derruba). "Loop" o repete sem parar. Exemplos em `scenarios/`
  (Wi-Fi de cafeteria, LTE->3G móvel, VPN congestionada, DNS falhando, servidor de jogo sobrecarregado,
  upload interrompido no meio, backend/API bloqueado). "Load scenario...", "Clear" e "Loop" agem no
  START, então ficam travados enquanto uma sessão roda. "Apply changes" durante um cenário funciona:
  veja [Formato do arquivo de cenário](#formato-do-arquivo-de-cenário).

**Profiles** - perfis prontos **ordenados do melhor (topo) ao pior (base)**: Perfect network, Good
Wi-Fi, 5G network, Home DSL (VDSL), LTE/4G, Satellite (low orbit), Distant server (another
continent), Weak Wi-Fi, Cafe (crowded Wi-Fi), Congested home link (bufferbloat), Train/metro
(tunnels), 3G network, Foreign roaming, Satellite (geostationary), In-flight Wi-Fi, 56k modem,
Terrible network - mais os seus próprios (salvos com um nome). O programa **sempre inicia em
"Perfect network"** (nada é degradado até você definir alguma coisa). Os perfis prontos incluídos não
podem ser excluídos - o botão "Delete" fica desativado para eles.

Os sem fio também perdem **em rajadas**, e não um pacote de cada vez, porque é isso que um enlace de
rádio faz: o desvanecimento do sinal, a interferência e as transferências entre antenas (handovers)
tiram o canal do ar por um trecho. Os com fio (DSL, 56k modem) mantêm a perda distribuída de modo
uniforme, porque nesse caso a perda é uma fila cheia, e não um rádio que sumiu.

Os números deles vêm de medições publicadas sempre que existem medições (as medianas do Ookla®
Speedtest® para satélite e celular, estudos revisados por pares para a reconfiguração de 15
segundos do Starlink, para o Wi-Fi de bordo e para quantos pacotes Wi-Fi se perdem em sequência).
Cada valor é atribuído no bloco de comentários no topo de `beantester/presets.py`, com os autores, o
veículo de publicação e um DOI, para que você possa conferir em vez de confiar. Onde não existe tal
valor - "Wi-Fi fraco" não é uma grandeza mensurável - o comentário ao lado do valor diz isso, em vez
de inventar uma fonte. Algumas delas merecem uma frase:

- **Satellite (low orbit)** - modelado no Starlink. O regime estável é bom (cerca de 40 ms de ping,
  100 Mbit/s). O que o torna distintivo é a reconfiguração a cada 15 segundos, que interrompe
  brevemente a transmissão e aparece como um pico de latência ocasional, e não como perda.
- **Distant server (another continent)** - um link rápido sem nada quebrado, só distante
  (~120 ms de ping). É este que expõe protocolos tagarelas e código que presume que o servidor está
  na porta ao lado.
- **Congested home link (bufferbloat)** - parado, parece bom (20 ms de ping). A degradação é a fila.
  ⚠️ **Ela só pega quando o seu aplicativo de fato satura o link**, porque o buffer faz parte do
  limitador de velocidade: envie um fio de tráfego de teste e você verá apenas um link comum de
  8 Mbit/s de download e 1 Mbit/s de upload, e nada mais. Sature o upload de 1 Mbit/s e veja o ping
  subir em direção a dois segundos - o caso "a chamada de vídeo morre quando alguém começa um backup".
- **Train/metro (tunnels)** - o único perfil que derruba o link por completo por segundos seguidos
  (3 s a cada 30), então o aplicativo precisa **reconectar**, e não apenas ficar mais lento.
- **In-flight Wi-Fi** - o clássico tipo via satélite: ~750 ms de ping e 7% de perda, que é a mediana
  medida, e não um pior caso. Aeronaves com equipamento mais novo de órbita baixa se comportam como
  "Satellite (low orbit)".

Um perfil armazena **como é o link**: perda, quanto dela chega em sequência, corrupção, duplicação,
latência, jitter, picos de latência, quedas do link (flapping), os limites de velocidade e o buffer.
Todo o resto - o alvo, o destino, o bloqueio, o RST, o MTU, a expiração do NAT, o agendamento, a
semente - fica de fora. Ao salvar um perfil, o programa avisa sobre os que você tem ligados no
momento. Use **"Save file..."** para a configuração completa. Escolher um perfil salvo ou um perfil
pronto define **todos** esses campos de uma vez, inclusive os que um determinado perfil pronto não
menciona - esses voltam ao padrão, então "Perfect network" realmente significa perfeita. Perfis
salvos por uma versão anterior carregam sem alterações.

Na CLI (`--preset`), um perfil pronto pode ser dado pelo seu **id canônico** ou por um **nome em
qualquer idioma da interface** (sem distinguir maiúsculas de minúsculas nem diacríticos do polonês -
`"Perfect network"` também funciona). Ids:
`presets.perfect`, `presets.good_wifi`, `presets.5g`, `presets.dsl`, `presets.lte`, `presets.leo`,
`presets.distant`, `presets.weak_wifi`, `presets.cafe`, `presets.bufferbloat`, `presets.metro`,
`presets.3g`, `presets.roaming`, `presets.satellite`, `presets.inflight`, `presets.modem56k`,
`presets.terrible`.

## Sintaxe de filtros (processo / IP / porta)

Três campos - **Target process**, **IP** e **port** (em "Target destination") - falam a mesma
minilinguagem. A mesma sintaxe será usada em todo campo de filtro que a ferramenta ganhar no futuro.
Ela funciona de forma idêntica na interface e na CLI (`--target`, `--dst-ip`, `--dst-port`).

### Elementos básicos

| Notação | Significado | Exemplo |
|---|---|---|
| `a,b,c` | **lista** - qualquer um dos valores combina | `80,443` |
| `a-b` | **faixa**, com os dois extremos **incluídos** | `8000-8100`, `10.0.0.1-10.0.0.50` |
| `>` `<` `>=` `<=` | **comparação** (numérica, para IP pelo valor do endereço) | `>1024`, `<=80`, `>10.0.0.5` |
| `!` | **exclusão** - "diferente de" | `!53` |
| `*` `?` | **curinga** (`*` = qualquer sequência, `?` = um caractere) | `chrome*`, `192.168.1.*` |
| `re:` | **expressão regular** (`re` do Python, sem distinguir maiúsculas de minúsculas) | `re:^chrome\.exe$` |
| `x.x.x.x/n` | **CIDR** (somente no campo IP) | `192.168.1.0/24`, `2001:db8::/32` |

Um campo vazio = **tudo** (sem filtragem). Espaços em volta de vírgulas e termos são ignorados.

### Como os termos se combinam

```
matches = (no positive terms OR any positive term matches) AND no "!" term matches
```

Em outras palavras: **os positivos se somam (OR), as exclusões subtraem (AND NOT)**. A ordem dos
termos não importa - `80,!53` significa exatamente o mesmo que `!53,80`.

| Entrada | Significa |
|---|---|
| *(vazio)* | tudo |
| `443` | somente a porta 443 |
| `80,443` | somente 80 **ou** 443 |
| `!53` | **tudo, exceto** 53 (não há termo positivo) |
| `!53,!443` | tudo, exceto 53 e 443 |
| `1000-2000,!1500` | 1000-2000, mas sem o 1500 |
| `>1024,!3389` | tudo acima de 1024, mas não o 3389 |
| `80,443,8000-8100,>9000,!8080` | 80, 443, 8000-8100 e tudo acima de 9000 - exceto 8080 |

### O campo "Target process"

Um termo pode ser um **nome** ou um **PID** - você pode misturá-los em um só campo.

* Um **nome** (sem `*` e sem `re:`) funciona como uma **substring sem distinguir maiúsculas de
  minúsculas**: `chrome` pega `chrome.exe` **e** `chromedriver.exe`. (Sempre funcionou assim -
  mantido de propósito para que configurações e perfis antigos continuem funcionando.)
* Um **PID** - um número puro (`12345`), uma faixa (`1000-2000`) ou uma comparação (`>1000`).
* **Curinga** e **`re:`** combinam com o **nome** do processo.
* As comparações `>` `<` `>=` `<=` só fazem sentido para um **PID** (números). `>chrome` é um
  **erro** - a ferramenta avisa isso explicitamente, em vez de não combinar com nada em silêncio.

```
chrome.exe                     all processes with "chrome.exe" in the name
chrome, !chromedriver          chrome but NOT chromedriver
chrome.exe, firefox.exe        two apps at once
12345                          a specific PID
12345, 6789                    two PIDs
1000-2000                      all processes with a PID in that range
>1000                          all processes with a PID > 1000
firefox*                       a name starting with "firefox"
re:^(chrome|firefox)\.exe$      exactly chrome.exe or firefox.exe
firefox, 12345                 a name and a PID in one field
```

Todos os processos que combinam contribuem com as suas portas locais - o direcionamento cobre a
**união** das portas deles. O conjunto de portas é mantido atualizado durante a sessão a partir dos
eventos de socket do sistema, então as novas conexões abertas do processo são capturadas assim que
abrem (sem o WinDivert de verdade, recorre a reexaminar a tabela de sockets algumas vezes por
segundo).

**O que "as suas portas locais" significa na prática.** Um pacote carrega endereços e portas, nunca
o nome de um programa, então a ferramenta não consegue combinar direto com "Chrome". Ela descobre
quais portas **locais** o processo possui e combina cada pacote pela porta local dele.

É por isso que o `443` nunca aparece aqui. Quando o Chrome carrega uma página, o `443` é a porta do
**servidor** - a ponta do próprio Chrome nessa conexão é uma porta temporária como `15597`, e esse
número pertence a um processo por vez, então o tráfego dele é capturado com exatidão.

Algumas portas funcionam de outro jeito. O mDNS (5353), o SSDP (1900) e o DHCP (67/68) são mantidos
por vários programas ao mesmo tempo, porque é assim que os programas encontram dispositivos na sua
rede. Ali o número da porta já não diz de quem é o tráfego, então é tudo ou nada: ou tudo o que passa
por aquela porta é degradado, ou nada. O log avisa quando isso acontece e informa qual das duas
situações vale. O tráfego comum não é afetado.

### O campo "IP"

**IPv4 e IPv6** são suportados. Uma regra nunca combina com um endereço da outra família - uma regra
IPv4 não pega um endereço IPv6 e vice-versa (você pode misturá-los com segurança em um só campo).

```
1.2.3.4                        one address
1.2.3.4, 8.8.8.8               two addresses
10.0.0.1-10.0.0.50             a range (both ends inclusive)
10.0.0.1-10.0.0.50, !10.0.0.7  a range with a hole
192.168.1.0/24                 a whole subnet (CIDR)
192.168.1.*                    the same via wildcard
!8.8.8.8                       everything except 8.8.8.8
>10.0.0.5                      addresses "greater" than 10.0.0.5
2001:db8::/32                  an IPv6 subnet
2001:db8::1-2001:db8::ff       an IPv6 range
10.0.0.0/8, 2001:db8::/32      IPv4 and IPv6 in one field
re:^10\.                        anything starting with 10.
```

A notação do endereço não importa: `2001:0db8:0000:0000:0000:0000:0000:0001` e `2001:db8::1` são o
mesmo endereço para a ferramenta.

### O campo "port"

```
443                            one port
80,443                         a list
8000-8100                      a range (both ends inclusive)
>1024                          high ports
<=1024                         privileged ports
!53                            everything except DNS
80,443,8000-8100,!8080         a mix
```

A faixa permitida é **0-65535**. `99999` é um erro, e não algo ignorado em silêncio.

### Expressões regulares (`re:`)

O prefixo `re:` é **obrigatório** - sem ele, um termo é um valor simples. Assim, `chrome.exe` é um
nome de arquivo (um ponto é um ponto), e não um padrão de regex.

| Padrão | Pega |
|---|---|
| `re:^chrome` | nomes que começam com `chrome` |
| `re:^chrome\.exe$` | **exatamente** `chrome.exe` (não `chromedriver.exe`) |
| `re:^(chrome\|firefox)\.exe$` | exatamente `chrome.exe` ou `firefox.exe` |
| `re:(node\|python)` | nomes que contêm `node` ou `python` |
| `re:^\d+$` | (em um campo de porta/PID) um número puro |
| `re:^10\.` | (em um campo de IP) endereços que começam com `10.` |
| `!re:^chrome` | **tudo, exceto** nomes que começam com `chrome` |

Os padrões **não distinguem maiúsculas de minúsculas** e procuram uma correspondência em qualquer
posição (`re.search`) - se você quer uma correspondência do início ao fim, use `^` e `$`.

**Uma vírgula dentro de uma regex precisa ser escapada com uma barra invertida** (`\,`), porque a
vírgula separa os termos:

```
re:^ch.{1\,8}e\.exe$          correct - {1,8} with a backslash before the comma
re:^ch.{1,8}e\.exe$           WRONG - it is split into "re:^ch.{1" and "8}e\.exe$"
```

### Casos que costumam confundir

* **`chrome` também pega `chromedriver`, mas `chrome.exe` não.** Um nome puro é uma *substring*: o
  texto "chrome" aparece em `chromedriver.exe`, mas o texto "chrome.exe" não (ali é `chrome` +
  `driver.exe`). Então `chrome.exe` -> apenas `chrome.exe`. `chrome` -> `chrome.exe`
  **e** `chromedriver.exe`.
* **`chrome*` é mais amplo do que parece.** O asterisco é "qualquer sequência", então `chrome*` pega
  `chromedriver.exe` exatamente como `chrome`. Quer exatamente um aplicativo? Use
  `re:^chrome\.exe$` ou acrescente uma exclusão: `chrome, !chromedriver`.
* **`8*` em um campo de porta é um curinga sobre o texto do número**, então pega `8`, `80`, `8080` e
  `8443` - mas **não** `443`. Quase sempre você queria uma faixa: `8000-8999`. Use curingas de porta
  de propósito.
* **`80,443,!8080` é só `80,443`.** Uma exclusão que não corta nada não é um erro - é simplesmente
  inútil.
* **`!53` também cobre o tráfego sem porta** (por exemplo, ICMP/ping). "Tudo, exceto 53" significa,
  literalmente, "tudo o que não é a porta 53", e um pacote ICMP não é a porta 53. Se você quer
  apenas TCP/UDP, restrinja o **Traffic filter**.
* **Um termo vazio é um erro**, e não "tudo": `80,,443` e `80,!` são rejeitados. Um **campo inteiro**
  vazio significa "tudo".
* **IP e porta se combinam com AND.** `IP=10.0.0.0/8` + `port=443` significa "tráfego para a rede
  10.x **e ao mesmo tempo** na porta 443". Quer "um ou outro"? Deixe o outro campo vazio e faça duas
  execuções.
* **`>chrome` é um erro.** As comparações funcionam com números (PID), não com nomes.
* **`2000-1000` é um erro** (faixa invertida), e não um conjunto vazio.
* **Um curinga não é uma regex.** Em `chrome*`, o asterisco significa "qualquer sequência". Em
  `re:chrome*`, significa "a letra `e` repetida 0 ou mais vezes". Se você escreve `re:`, escreve uma
  regex.
* **Uma repetição dentro de uma repetição é recusada por ser lenta demais**, por exemplo
  `re:^(\w+)+$` ou `re:^([0-9:]+)+$`. Um padrão assim pode levar segundos em um único nome ou
  endereço que quase combina, e um endereço é verificado a cada pacote. Escreva a repetição uma só
  vez: `re:^\w+$`.

Todo erro de sintaxe é informado **imediatamente**: na interface, o campo fica vermelho com o motivo
abaixo (no idioma da interface), e a CLI termina com um `error: ...` legível - nunca um "nada
funciona" silencioso.

## Estatísticas (o que os contadores significam)

O gráfico de vazão tem um eixo Y com valores (KB/s), uma grade, uma escala arredondada de forma
"bonita" e indicadores atuais de down/up no canto. Download/Upload (KB/s ao vivo), Packets (quantos
passaram), Queued (esperando - cresce com o atraso/limite), Lost, Loss runs (em quantas RAJADAS
essa perda chegou - veja "Losses in a row"), Corrupted, Duplicated, Buffer overflow (descartados
quando a ferramenta está sobrecarregada), Dropped at stop (ainda estavam na fila quando o STOP foi
pressionado), Send failed (a ferramenta os capturou, mas não conseguiu devolvê-los ao fio - a conexão
caiu ou o driver recusou), Rate-limit drop (descartados por um buffer cheio do limite de velocidade -
contado separadamente da perda e do "Buffer overflow"), SYN dropped, MTU dropped, NAT expired, RST
torn, LAN: internet cut off, Local network cut, RST sent.

**Copiando os números.** Clique com o botão direito em qualquer valor em "Live" ou "Session" para
copiar aquele valor, ou a aba inteira. Cada painel também tem um botão - "Copy counters" sob a
grade, "Copy session details" ao lado dos botões de reprodução - que copia cada linha exatamente
como aparece na tela, com legendas e unidades. Útil para um relatório de bug: o painel da sessão
traz o nome do computador, os endereços dele, a semente e o que a captura cobriu.

Os três últimos desses - "Buffer overflow", "Dropped at stop" e "Send failed" - são a ferramenta
perdendo os seus pacotes, e não o link que você pediu para ela simular. Eles são contados, mantêm
honesta a aritmética de vistos/entregues/descartados e, de propósito, **não** fazem parte da
"Effective loss". Qualquer um deles diferente de zero significa que parte da perda que você está
medindo é nossa.

### Reproduzindo um bug (o painel "Session and reproduction")

Projetado para que, depois de um bug, você possa recriar exatamente as mesmas condições:

- **Seed (effective)** - mesmo que você deixe o campo Seed vazio, o programa sorteia e lembra uma
  semente concreta. Digite-a depois no campo Seed e execute de novo para obter os mesmos sorteios.
- **Oscilação repetível** - o padrão de queda do link é medido a partir do início da sessão, então
  com as mesmas configurações ele se repete de forma idêntica entre execuções (não depende do relógio
  do sistema).
- **O que a semente reproduz** - a semente reproduz as **decisões** do motor (quais pacotes são
  descartados, corrompidos, duplicados, e quanto são atrasados), e não a **contagem de pacotes**. O
  tráfego que cruza o link depende do que os seus aplicativos e o sistema fazem naquele momento,
  então duas execuções com a mesma semente dão as mesmas *proporções* (por exemplo, 15,8% de perda
  nas duas), mas não contadores idênticos ao pacote. Para comparações em CI, use taxas (%), não
  contagens brutas de pacotes.
- **Start / Duration / Effective loss / Queue peak / Down-up peak** - um retrato rápido da execução.
- **O que a "Effective loss" conta** - a parcela do tráfego que você mirou e que **esta ferramenta**
  quebrou, em **todas** as degradações: a Loss configurada mais descartes por limite de velocidade,
  bloqueio, corte de LAN, corte da rede local, quedas do link, resets de conexão, descartes de SYN,
  descartes por MTU e expiração de NAT. Com um alvo definido, só o tráfego do alvo conta, então
  outros aplicativos não conseguem diluí-la. Os pacotes que a **ferramenta** jogou fora ficam de fora
  de propósito - "Buffer overflow", "Dropped at stop" e "Send failed" são falhas dela, não do link, e
  têm os seus próprios contadores. O `effective_loss_pct` do relatório é o mesmo número, ao lado de
  `packets_in_scope`.
- **Driver queue wait (peak)** - o maior tempo que um pacote **já** tinha esperado dentro do
  WinDivert quando esta ferramenta o recebeu. É medido, não estimado: o driver carimba cada pacote
  com a hora da captura, e a ferramenta amostra isso 20 vezes por segundo. Em uma máquina ociosa, é
  uma fração de milissegundo (medido aqui: 0,05-0,16 ms). Se crescer, a ferramenta está adicionando
  um atraso que não aparece em nenhum outro contador, porque acontece na fila do driver, antes da
  dela - e quando chega a 50 ms, ela avisa no log e na lista de eventos. Em branco com `--simulate`,
  que não tem driver.
- **Ele mede esta máquina, não a internet.** A ferramenta vê os pacotes que cruzam a pilha de rede
  deste computador, então um pacote perdido lá fora na rede - a resposta que nunca voltou - nunca
  chega aqui e nada aqui consegue contá-lo. Um ping limpo de 30 pacotes que perde uma resposta mostra
  **59** pacotes na linha da conexão e **zero** descartes, e os dois números estão certos: 30
  requisições saíram, 29 respostas voltaram, e a ferramenta não quebrou nenhuma delas. A perda de
  ponta a ponta é para os números do próprio aplicativo (ou o "Lost" do `ping`).
- **Data used** - Downloaded / Uploaded / Total (MB) acumulados desde o início, mais a vazão média da
  sessão. Você sabe na hora quantos dados o aplicativo usou. (O relatório também tem "attempted MB" -
  quanto o aplicativo queria enviar antes de a perda e os limites serem subtraídos.)
- **Event log** com carimbos de data e hora: início, mudanças de configuração, etapas de cenário,
  derrubadas e as suas marcações de bug - com **ordenação** ao clicar no cabeçalho de uma coluna.
- **Marcar o momento de um bug** - clique exatamente quando você vir o bug. Isso insere uma marcação
  com data e hora no log.
- **Salvar o relatório de reprodução** - um único arquivo JSON com tudo: semente, todas as
  configurações, contadores, métricas, registro de eventos, conexões e um **comando de CLI pronto**
  que recria as condições. Ele também registra **a fila do WinDivert atrás da qual a sessão rodou**
  (`session.driver_queue`: tamanho, tempo e volume). Essa é a fila do próprio driver, antes da fila
  desta ferramenta, e os três valores são tetos, e não um atraso fixo: enquanto a ferramenta dá
  conta, os pacotes quase não esperam nela (veja **Driver queue wait (peak)** acima). Ela só enche
  quando a ferramenta fica para trás. Aí os pacotes esperam mais e, quando ela está cheia, o driver
  os descarta antes que esta ferramenta os veja. Uma fila menor não removeria essa espera, apenas a
  transformaria em pacotes perdidos que nenhum contador consegue mostrar, então a ferramenta deixa as
  configurações do próprio driver em paz. Um relatório de uma máquina que você não tem à sua frente
  diz qual fila produziu os seus números. Os mesmos três valores vão para o log no START.
- **Copy CLI command** - direto para a área de transferência: `BeanNetworkTester.exe --seed ... --loss ...
  --duration ...` (o comando se adapta à versão: a partir do repositório você obtém
  `python bean_network_tester.py ...`).
- **O que o relatório e o comando descrevem** - a última sessão, e não o formulário: as
  configurações que o START lhe deu, atualizadas por cada "Apply changes", com a sua semente e o seu
  cenário (`--scenario`, mais `--loop` se ele repetiu em laço). Uma mudança que você digitou mas não
  aplicou fica de fora, e o mesmo vale para um perfil carregado depois do STOP. Durante um cenário,
  "Apply changes" passa a ser a base sobre a qual as etapas seguintes constroem, então o comando
  também leva essas configurações. Um cenário que acompanha o programa é nomeado a partir da pasta
  do programa (`scenarios\...` a partir do código-fonte, `_internal\scenarios\...` ao lado do
  `.exe`), e o comando o encontra a partir de qualquer pasta em que você o execute. Qualquer outro
  arquivo é nomeado pelo caminho que você escolheu.
  Antes da primeira sessão, **Copy CLI command** copia as configurações do formulário.

## Arquivo de configuração

Os botões "Save/Load file" gravam todas as configurações em JSON. O mesmo arquivo funciona na CLI
com `--config`. Ordem de precedência: padrões < arquivo < perfil < flags.

Cada valor é verificado quanto ao tipo quando o arquivo é lido, e uma etapa de cenário é verificada
da mesma forma. Uma chave liga/desliga (`lan_mode`, `internet_only`, `narrow_filter`...) é `true` ou
`false`, ou `1` ou `0`. O texto `"false"` é recusado, e não lido como "ligado". `filter` é uma das
opções de `--filter`, e `seed` é um número inteiro (`-1` para um aleatório). Um valor do tipo errado
interrompe a CLI com o código `3` e nomeia a configuração. A janela mostra a mesma mensagem e deixa
o formulário como estava.

## Modo de linha de comando (CLI)

A CLI roda **a partir do mesmo `BeanNetworkTester.exe`** da interface: iniciá-lo com qualquer
argumento inicia o modo de texto (sem janela, sem tkinter), e sem argumentos - a interface gráfica.
As mensagens e o `--help` estão sempre em inglês.

```bat
:: GUI
BeanNetworkTester.exe

:: CLI (from the same exe)
BeanNetworkTester.exe --loss 5 --latency 100 --down 1024 --target chrome.exe
BeanNetworkTester.exe --preset "3G network" --duration 60
```

> Trabalhando a partir do repositório (sem compilar)? Em todo lugar, troque `BeanNetworkTester.exe`
> por `python bean_network_tester.py` - todas as flags e códigos de saída são idênticos.

### Códigos de saída (o contrato de CI/CD)

Cada forma de terminar tem o seu próprio código - um pipeline não precisa interpretar texto:

| Código | Nome | Quando |
|---|---|---|
| `0` | ok | a sessão rodou e todas as verificações passaram |
| `1` | runtime | não foi possível iniciar (sem `pydivert`, driver, falha do motor) |
| `2` | usage | linha de comando incorreta (flag desconhecida, tipo errado) - o código do argparse |
| `3` | config | configurações inválidas: expressão, agendamento, faixa, perfil, arquivo de configuração |
| `4` | scenario | o arquivo de cenário não existe ou está malformado |
| `5` | io | não foi possível gravar um artefato (relatório de reprodução, configuração salva) |
| `6` | assertion | a execução teve êxito, mas `--min-packets` / `--fail-on-no-traffic` não passou |
| `7` | permission | são necessárias permissões de administrador (Windows), ou root ou CAP_BPF, CAP_NET_ADMIN e CAP_NET_RAW (Linux), e elas estão faltando |
| `130` | interrupted | Ctrl+C (SIGINT) |
| `143` | terminated | SIGTERM (cancelamento de job, `docker stop`), Ctrl+Break ou o fechamento da janela do console |

`BeanNetworkTester.exe --help` imprime os mesmos códigos.

### Saída: logs no stderr, dados no stdout

- **stderr** - o log para humanos, com o prefixo `[bean]` (início, semente, erros, motivo da parada),
- **stdout** - dados: linhas de relatório e, com `--format json`, **NDJSON** (um objeto JSON por
  linha: objetos `sample` sucessivos e um `summary` final com o código de saída, a semente e o
  comando de reprodução).

```bat
BeanNetworkTester.exe --simulate --duration 30 --format json > run.ndjson
```

### Todos os parâmetros da CLI

**Degradação do link**

| Flag | Unidade | Descrição |
|---|---|---|
| `--loss` | % | porcentagem de pacotes descartados |
| `--loss-burst` | pacotes | número médio de pacotes perdidos em sequência (0 = perda distribuída uniformemente). Dá forma à `--loss`, não se soma a ela |
| `--corrupt` | % | porcentagem de pacotes com um bit invertido |
| `--dup` | % | porcentagem de pacotes enviados duas vezes |
| `--latency` | ms | atraso fixo adicionado a cada pacote |
| `--jitter` | ms | variação aleatória do atraso (+/-) |
| `--down` `--up` | KB/s | limite de vazão (0 = sem limite) |
| `--buffer` | ms | buffer do link para o limite de velocidade (0 = sem limite). Limita o atraso de fila, o excesso vai como "Rate-limit drop" |
| `--spike-prob` `--spike-ms` | % / ms | com a probabilidade dada, acrescenta um atraso extra |
| `--syn-drop` | % | porcentagem de pacotes TCP SYN descartados |
| `--max-size` | B | "buraco negro de MTU" - descarta pacotes maiores que N bytes (0 = desligado) |
| `--nat-timeout` | s | depois de N s de silêncio, o mapeamento do NAT "desaparece" (0 = desligado) |
| `--rst-prob` `--rst-cooldown` | % / s | porcentagem de conexões derrubadas com RST e por quanto tempo a derrubada é mantida |
| `--flap-period` `--flap-down` | s / % | queda cíclica do link: com que frequência e por qual fração do período |
| `--rate-schedule` | - | vazão variável: `"time:download:upload,..."` em KB/s, em laço. Tempo acima de 0 e no máximo 86400 s, velocidades de 0 (sem limite) a 10000000 |
| `--asym` | - | dá ao upload os seus próprios valores. Sem ela, um só conjunto de números vale nos dois sentidos, que é o padrão |
| `--loss-up` `--corrupt-up` `--dup-up` | % | as mesmas três degradações, para os pacotes que esta máquina ENVIA. Usadas somente com `--asym` |
| `--latency-up` `--jitter-up` | ms | o atraso e a sua variação, para os pacotes que esta máquina ENVIA. Usadas somente com `--asym` |
| `--spike-prob-up` `--spike-ms-up` | % / ms | o atraso ocasional mais longo, para os pacotes que esta máquina ENVIA. Usadas somente com `--asym` |
| `--ipv4-only` `--ipv6-only` | - | degrada apenas uma família de endereços. A outra continua fluindo intacta - isso mira a ferramenta, não bloqueia um protocolo. Funciona também com `--dst-ip` vazio, que significa todos os endereços. As duas flags juntas se excluem, nada é degradado, e o log avisa |
| `--lan-mode` | - | modo LAN: corta a internet (endereços públicos), mantém a rede local |
| `--internet-only` | - | o espelho: corta a rede local (10.x, 172.16-31.x, 192.168.x, link-local, CGNAT), mantém a internet. O loopback continua funcionando. Cuidado: o DNS perguntado ao seu roteador é tráfego local, então a internet pode parar de funcionar junto |
| `--narrow-filter` | - | empurra `--dst-ip`/`--dst-port` para dentro do filtro do WinDivert, para que o driver nunca entregue tráfego que não poderia ser degradado (bem mais rápido em altas taxas de pacotes). Apenas no START. Enquanto está ligada, as estatísticas e as conexões cobrem somente o tráfego restrito |

**Direcionamento** (as três aceitam a [sintaxe de filtros](#sintaxe-de-filtros-processo--ip--porta)
completa: listas, faixas, `!`, `>`, `<`, `>=`, `<=`, curingas, `re:`, e `--dst-ip` também aceita CIDR)

| Flag | Descrição | Exemplos |
|---|---|---|
| `--target` | processos: nome, PID, faixa de PIDs, curinga, regex | `--target chrome.exe`<br>`--target "chrome,!chromedriver"`<br>`--target ">1000"` |
| `--dst-ip` | endereços IP remotos (IPv4 e IPv6) | `--dst-ip 1.2.3.4`<br>`--dst-ip "10.0.0.1-10.0.0.50,!10.0.0.7"`<br>`--dst-ip "192.168.1.0/24"`<br>`--dst-ip "2001:db8::/32"` |
| `--dst-port` | portas remotas (0-65535) | `--dst-port 443`<br>`--dst-port "80,443,8000-8100"`<br>`--dst-port "!53"`<br>`--dst-port ">1024"` |
| `--filter` | qual tráfego capturar, afinal (IPv4 + IPv6): `both,out,in,tcp,udp,ping,loopback` | `--filter tcp` |

**Bloqueio (firewall)** - descarta todo o tráfego para os destinos escolhidos. O bloqueio dispara por **IP OU porta** (um campo vazio é ignorado, então `--block-port 443` sozinho bloqueia a 443 para qualquer endereço). A mesma [sintaxe de filtros](#sintaxe-de-filtros-processo--ip--porta) de cima. Respeita o direcionamento por processo (bloqueia apenas o tráfego do alvo).

| Flag | Descrição | Exemplos |
|---|---|---|
| `--block-ip` | bloqueia endereços IP remotos (IPv4 e IPv6) | `--block-ip 1.2.3.4`<br>`--block-ip "10.0.0.0/8,!10.0.0.1"` |
| `--block-port` | bloqueia portas remotas (0-65535) | `--block-port 443`<br>`--block-port "80,443,8000-8100"` |
| `--block-reject` | recusa as conexões TCP bloqueadas em vez de descartá-las em silêncio | `--block-port 443 --block-reject` |

**Recusada ou ignorada** - por padrão, uma conexão bloqueada não recebe resposta nenhuma, e o
programa que você está testando espera até desistir por conta própria. Com `--block-reject`, ela é
recusada, então o programa informa "connection refused" em cerca de dois segundos, exatamente como
faria com uma porta que está de fato fechada. São dois caminhos de código diferentes na maioria dos
aplicativos, e uma suíte de testes que só viu um deles só testou um deles. A recusa cobre as
**conexões que este computador inicia, sobre TCP**: o tráfego sobre UDP e as conexões que chegam de
fora continuam sendo bloqueados em silêncio.

> No `cmd.exe`/PowerShell, **coloque a expressão entre aspas** se ela contiver vírgula, `!`, `>`, `<`,
> `*` ou `^` - caso contrário o shell a interpreta à maneira dele (o `cmd.exe` descarta um `^` solto,
> então `re:^edge` chegaria como `re:edge`). O comando que recria a sessão
> (`Copy CLI command` e a linha `Reproduce:`) coloca as aspas para você.

**Execução e relatórios**

| Flag | Descrição |
|---|---|
| `--preset NAME` | perfil pronto por id canônico ou por um nome em qualquer idioma da interface |
| `--config FILE` / `--save-config FILE` | carrega / salva as configurações (JSON, compartilhado com a interface) |
| `--scenario FILE` `--loop` | um cenário em linha do tempo (JSON) e a sua repetição em laço |
| `--seed N` | semente de aleatoriedade - a mesma execução pode ser repetida |
| `--duration N` | **tempo de execução em segundos** (0 = até o Ctrl+C, ou até a linha do tempo de um `--scenario` acabar). O mesmo campo existe na interface ("Session") |
| `--row-limit N` | uma configuração **só da interface**: máximo de linhas nas tabelas (0 = sem limite, padrão 50 000). Na CLI sem janela (headless) não faz nada - só é salva no arquivo de configuração e passa a valer quando esse arquivo é aberto na interface. O equivalente do campo "Row limit" |
| `--interval N` | com que frequência reportar, em segundos (maior que 0, no máximo 86 400 - o mesmo teto que o `--duration` tem, então um intervalo que nunca poderia disparar é recusado em vez de aceito) |
| `--log-conns` | imprime as conexões observadas no final |
| `--repro-out FILE` | salva um relatório de reprodução (JSON) |
| `--simulate` | tráfego sintético em vez do WinDivert (teste sem Windows, sem driver, sem administrador) |
| `--gui` | abre a interface gráfica. Válida **apenas sozinha** - a interface tem os seus próprios controles, então combiná-la com flags de configuração é um erro de uso (saída 2) em vez de uma execução headless silenciosa |
| `--version` | imprime a versão e sai |

**Saída e diagnósticos**

| Flag | Descrição |
|---|---|
| `-v`, `--verbose` | registra o que o programa faz: configurações efetivas, filtros compilados, portas de processos resolvidas, etapas de cenário, abertura/fechamento do driver |
| `-q`, `--quiet` | somente erros: sem log e sem relatórios periódicos |
| `--log-level {error,warn,info,debug}` | nível de log explícito (sobrepõe `-v`/`-q`) |
| `--log-file FILE` | também acrescenta o log (e os relatórios) a um arquivo - um artefato de CI pronto |
| `--format {text,json}` | formato do stdout: texto para humanos ou NDJSON para um pipeline |

**Para CI/CD**

| Flag | Descrição |
|---|---|
| `--dry-run` | verifica a configuração e sai (não toca no driver, não passa tráfego) - ideal para validar arquivos de configuração em um pipeline. Um `--scenario` também é lido e validado, para que o ensaio e a execução real concordem |
| `--print-config` | imprime as configurações efetivas (depois de `defaults < file < preset < flags`) como JSON e sai |
| `--min-packets N` | sai com o código `6` se menos de N pacotes foram capturados |
| `--fail-on-no-traffic` | atalho para `--min-packets 1` - **pega um filtro que não capturou nada** |
| `--doctor` | verifica o ambiente (administrador, `pydivert`, estado do driver WinDivert, sobras em `%TEMP%`, se a pasta do programa pode ser gravada sem permissões de administrador, com que precisão o relógio mede o tempo) e sai |
| `--cleanup-driver` | descarrega um driver WinDivert travado (libera o arquivo `.sys` bloqueado **sem reiniciar o sistema**) e sai. Cada linha diz o que aconteceu com um serviço. O código de saída é `0` mesmo quando um serviço não pôde ser parado |

Ordem de precedência: **defaults < `--config` < `--preset` < flags**. Lista completa:
`BeanNetworkTester.exe --help`.

### Exemplos de direcionamento

```bat
:: only the browser, but not its test driver
BeanNetworkTester.exe --loss 10 --target "chrome,!chromedriver"

:: only HTTPS traffic to a test server and its backup address
BeanNetworkTester.exe --latency 300 --dst-ip "10.0.0.5,10.0.0.9" --dst-port 443

:: the whole test subnet except one host, on application ports
BeanNetworkTester.exe --down 128 --dst-ip "10.0.0.0/24,!10.0.0.1" --dst-port "8000-8100"

:: everything EXCEPT DNS (so name resolution works while the rest breaks)
BeanNetworkTester.exe --loss 20 --dst-port "!53"

:: high-PID processes, traffic to IPv6
BeanNetworkTester.exe --jitter 80 --target ">1000" --dst-ip "2001:db8::/32"
```

### Exemplos de bloqueio (firewall)

```bat
:: cut the app off from an external API (the server is "down")
BeanNetworkTester.exe --block-ip 203.0.113.10

:: block all HTTPS - see how the app copes with no connection
BeanNetworkTester.exe --block-port 443

:: block several ports OR the whole backend subnet (blocking is IP OR port)
BeanNetworkTester.exe --block-port "8080,9090" --block-ip 203.0.113.0/24

:: impair only your app's traffic, and cut its link to the payment server entirely
BeanNetworkTester.exe --latency 200 --target myapp.exe --block-ip 198.51.100.7
```

### O modo `--simulate` (teste sem Windows e sem administrador)

Uma prévia com tráfego sintético - não precisa do WinDivert nem de privilégios:

```bat
BeanNetworkTester.exe --simulate --down 500 --loss 10 --duration 4 --interval 1
```

### Repetibilidade e cenários pela CLI

```bat
BeanNetworkTester.exe --simulate --seed 42 --loss 20 --duration 10
BeanNetworkTester.exe --simulate --scenario scenarios/cafe-wifi.json
```

`scenarios/<name>.json` (ou `_internal\scenarios\<name>.json`) abre, a partir de qualquer pasta, um
cenário que acompanha o programa. Se a pasta atual tiver um arquivo nesse caminho, esse arquivo é
usado.

A semente garante **decisões por pacote** idênticas para a mesma sequência de pacotes. As etapas de
cenário são cumulativas (cada uma altera o estado), e `action: reset_tcp` derruba as conexões TCP
naquele momento. O arquivo de cenário é **validado quando você o abre** - um JSON qualquer termina
com um erro legível, e não com um "cenário com 0 etapas", e as configurações de uma etapa são
verificadas pelas mesmas regras que o formulário usa, então um valor que o programa não consegue
usar é nomeado com o número da sua etapa, em vez de interromper a execução no meio.

Toda execução da CLI termina imprimindo a **semente efetiva** e um comando pronto para reproduzi-la -
com o arquivo de `--scenario` como você o digitou, `--loop` e `--simulate` quando a execução os
tinha - e `--repro-out file.json` salva o relatório de reprodução completo com o mesmo comando.

## Colunas de Connections

Dezessete colunas, todas ordenáveis ao clicar no cabeçalho, e cada uma com a mesma explicação em uma
dica no cabeçalho.

| coluna | o que contém |
|---|---|
| `process` | O processo dono da porta local. `?` significa que o nome não pôde ser resolvido - execute como administrador. |
| `PID` | O id do processo dono da porta local, resolvido quando o pacote foi capturado. |
| `proto` | Protocolo de transporte: TCP / UDP / ICMP / IP. |
| `remote IP` | O endereço com o qual esta máquina está conversando. Clique com o botão direito em uma linha para limitar as degradações a ele. |
| `r.port` | Porta do lado remoto (443 = HTTPS, 53 = DNS, 80 = HTTP). Vazia para tráfego sem portas, como o ping. |
| `l.port` | Porta nesta máquina - o que liga a conexão a um processo. Vazia para ping/ICMP, e é também por isso que essas linhas costumam não ter nome de processo. |
| `packets` | Pacotes vistos nesta conexão desde que ela apareceu. |
| `impaired?` | Se a conexão estava **no escopo da degradação** nesta sessão - degradada, e não apenas observada. Continua `yes` depois que a conexão fecha, como registro. Sem direcionamento definido, tudo está no escopo. |
| `dropped` | Pacotes descartados nesta conexão pelas degradações ativas (perda, queda do link, modo LAN, "Internet only", resets, ...). |
| `down` | Dados que realmente **chegaram** ao aplicativo - o que ele baixou. A mesma quantidade que o painel da sessão chama de "Downloaded (MB)". |
| `up` | Dados que realmente **saíram** desta máquina - o que o aplicativo enviou. |
| `total` | Download entregue + upload entregue. |
| `down seen` | Dados que a ferramenta **capturou** na entrada, antes de qualquer degradação - o que a conexão ofereceu. |
| `up seen` | Dados que a ferramenta **capturou** na saída - o que o aplicativo tentou enviar. |
| `avg[B]` | Tamanho médio dos pacotes nesta conexão (total de bytes / pacotes). |
| `time[s]` | Segundos entre o primeiro e o último pacote desta conexão nesta sessão. |
| `idle[s]` | Segundos desde o último pacote. Para de contar quando a sessão para. |

**As cinco colunas de tráfego carregam a própria unidade.** Cada célula é mostrada em B, KB, MB ou
GB, conforme o que couber, então um fluxo de 5 GB aparece como `5.00 GB` em vez de `5242880.0`, e uma
resposta de DNS de noventa bytes aparece como `90 B` em vez de `0.0`. O rodapé sob a tabela faz o
mesmo com os seus totais. `avg` é o tamanho de um pacote e fica em bytes. A ordenação e a exportação
para CSV não são afetadas - ambas trabalham com a contagem bruta de bytes, nunca com o texto da
célula.

**O par entregue/visto é o ponto central da tabela.** Sem nada degradado, os dois são iguais. Adicione
perda ou um limite de velocidade e eles se separam, e **a diferença entre os dois é o estrago feito
naquela conexão**. (Antes de serem separados havia um único par, com os bytes capturados sob
títulos que significavam entregues: uma linha podia mostrar 5 MB recebidos enquanto o aplicativo
havia recebido 0,4 MB.)

## Exportações em CSV

Dois botões gravam dois arquivos, e eles se comportam **de forma diferente de propósito**. Ambos vão
para a sua própria pasta, `%LOCALAPPDATA%\BeanNetworkTester`, junto com os seus perfis e o estado da
janela (ou para a raiz do projeto, quando executado a partir do código-fonte). O programa escreve o
caminho completo no log a cada vez que salva um deles. Eles ficam fora da pasta do programa para que
atualizar o programa - à mão ou por um gerenciador de pacotes, que substitui essa pasta - não leve os
seus arquivos junto. Defina `BEAN_DATA_DIR` com uma pasta de sua escolha para manter tudo em outro
lugar, por exemplo no mesmo pen drive de uma cópia portátil.

A pasta pertence à conta do Windows com a qual o programa está rodando. Em uma conta sem permissões
de administrador, aceitar o pedido de elevação executa o programa como a conta de administrador cuja
senha foi digitada, e ele passa a usar a pasta DESSA conta - então os perfis que você salvou sem
elevação não são os que você vê com ela. "About" e `--doctor` imprimem a pasta em uso, para que você
sempre saiba qual está olhando. Para dar a todas as contas da máquina uma pasta compartilhada, um
administrador pode definir `BEAN_DATA_DIR` como variável de ambiente do sistema.

| | **Statistics** ("Export CSV", Statistics -> Live) | **Connections** ("Export connections CSV") |
|---|---|---|
| arquivo | `bean_network_tester_stats.csv` | `bean_network_tester_connections.csv` |
| modo | **Acrescenta** uma linha a cada clique - um registro com o qual você pode montar um gráfico entre execuções | **Sobrescreve** - um instantâneo da tabela como ela está agora |
| gravação | de forma atômica (arquivo temporário + renomeação), então uma falha no meio da gravação não pode truncá-lo | igual |
| a sua busca / ordenação | não se aplica | **respeitadas** - o arquivo corresponde ao que você estava vendo |
| "Show only the targeted traffic" | **ignorado de propósito** - veja abaixo | **respeitado** |
| o campo "Row limit" | não se aplica | **ignorado** - todas as linhas filtradas são exportadas, não só as desenhadas |
| as colunas mudam entre versões | o arquivo antigo é renomeado com um carimbo de data e hora e um novo é iniciado, então as linhas nunca ficam desalinhadas sob um cabeçalho desatualizado | não se aplica |
| codificação | UTF-8 sem marca de ordem de bytes (BOM). Com um clique duplo, o Excel lê esse arquivo na página de código do Windows e estraga as letras fora dela (nomes de processos em polonês ou chinês). Abra-o por **Dados > Obter Dados > Do Arquivo > De Texto/CSV** e defina **Origem do Arquivo** como **65001: Unicode (UTF-8)** | igual |

O CSV de estatísticas não respeita a chave "show only the targeted traffic" porque é um registro de
acréscimo: um arquivo cujas colunas significam uma coisa em algumas linhas e outra nas demais é pior
que inútil para a planilha para a qual ele existe. Em vez disso, ele carrega **os dois** totais
(`bytes_in`/`bytes_out` e `delivered_in_scope_bytes_*`), para que você mesmo possa restringir e
ainda assim saber qual é qual. **"Capture only the targeted traffic" não pode ser desfeito desse
jeito** - ele muda o que o `packets_seen` contou desde o início - por isso toda linha o registra em
`capture_narrowed`.

### Colunas do CSV de estatísticas

`time`, o escopo de captura da sessão e depois cada contador, nesta ordem:

| coluna | significado |
|---|---|
| `time` | hora do relógio no momento do clique |
| `capture_narrowed` | `yes` quando "Capture only the targeted traffic" estava em vigor naquela sessão, então toda contagem da linha cobre **somente** o tráfego do seu destino. `no` significa que a linha cobre tudo o que o filtro de tráfego deixou passar. Sem esta coluna, duas linhas com o mesmo `packets_seen` poderiam descrever tráfegos completamente diferentes |
| `packets_seen` | pacotes capturados |
| `packets_in_scope` | destes, os que o direcionamento selecionou para degradação |
| `dropped_loss` | descartados pela configuração Loss |
| `loss_runs` | em quantas RAJADAS essa perda chegou (veja "Losses in a row"). 0 com um comprimento de rajada definido significa que a sessão foi curta demais para ver uma, ou que a perda é de 100% e não há rajadas separadas |
| `dropped_overflow` | descartados porque a fila da própria ferramenta estava cheia (veja a nota sobre ela abaixo) |
| `corrupted` | pacotes cujo conteúdo foi invertido |
| `duplicated` | cópias extras enfileiradas |
| `packets_reordered` | pacotes que saíram da ferramenta em ordem diferente da de entrada. 0 com jitter ou um pico configurado significa que os pacotes estavam distantes demais para que algum ultrapassasse outro. Contado por sentido, então duas conexões movimentadas podem se ultrapassar sem que nenhuma das pontas veja algo fora de ordem |
| `dropped_syn` | TCP SYNs descartados ("conexões que nunca abrem") |
| `dropped_mtu` | descartados por excederem o tamanho máximo (buraco negro de MTU) |
| `dropped_nat` | descartados porque o mapeamento do NAT havia expirado |
| `dropped_rst` | tráfego engolido enquanto uma conexão era mantida derrubada depois de um reset |
| `dropped_lan` | descartados pelo modo LAN (internet cortada, rede local viva) |
| `dropped_local_network` | descartados por "Internet only" (rede local cortada, internet e loopback vivos) |
| `dropped_block` | descartados pelos campos de bloqueio (firewall) |
| `dropped_link_outage` | descartados durante uma queda por oscilação do link |
| `dropped_rate_limit` | descartados por um buffer cheio do limite de velocidade |
| `dropped_at_stop` | pacotes enfileirados descartados quando a sessão parou |
| `dropped_send_failed` | o driver recusou reinjetá-los |
| `connections_reset` | conexões realmente derrubadas |
| `connections_refused` | conexões bloqueadas que foram recusadas em vez de ignoradas (`--block-reject`) |
| `rst_sent` | pacotes RST que chegaram à pilha |
| `bytes_in` / `bytes_out` | bytes entregues, todo o tráfego capturado |
| `bytes_in_total` / `bytes_out_total` | bytes capturados, antes da degradação |
| `delivered_in_scope_bytes_down` / `delivered_in_scope_bytes_up` | bytes entregues, somente o tráfego direcionado |
| `queue_len` / `queue_peak` | pacotes esperando na fila de atraso, agora e no pico |
| `driver_wait_peak_ms` | o maior tempo que o driver fez um pacote esperar antes de a ferramenta o ver, contado depois que a ferramenta está lendo (os pacotes capturados enquanto o START ainda se preparava ficam de fora) |

Os três últimos contadores de descarte - `dropped_overflow`, `dropped_at_stop`,
`dropped_send_failed` - são perdas da **própria ferramenta**, e não degradação que você pediu, e é
por isso que são contados à parte.

### Colunas do CSV de conexões

As mesmas linhas da tabela, mas **os cabeçalhos não são os rótulos da tabela** - eles escrevem por
extenso o que a tabela abrevia:

| Coluna do CSV | coluna da tabela |
|---|---|
| `process`, `pid`, `proto`, `remote_ip`, `remote_port`, `local_port`, `packets` | iguais, sem abreviação |
| `impaired` | `impaired?` (`yes` / `no`) |
| `dropped` | `dropped` |
| `delivered_down_bytes`, `delivered_up_bytes`, `delivered_total_bytes` | `down`, `up`, `total` - **sempre bytes brutos aqui**, nunca a unidade que a tela escolheu |
| `captured_down_bytes`, `captured_up_bytes`, `captured_total_bytes` | `down seen`, `up seen` (mais o total deles) |
| `avg_bytes` | `avg[B]` |
| `duration_s`, `idle_s` | `time[s]`, `idle[s]` |

## Formato do arquivo de cenário

Um cenário é uma linha do tempo: uma lista de etapas, cada uma com um tempo em segundos e o que fazer
naquele momento. O arquivo é JSON, seja um objeto ou uma lista simples de etapas:

```json
{
  "loop": true,
  "steps": [
    { "at": 0,  "settings": { "latency": 20, "jitter": 15, "loss": 1, "down": 1024, "up": 256 } },
    { "at": 20, "settings": { "loss": 3, "down": 512 } },
    { "at": 45, "action": "reset_tcp", "duration": 5 },
    { "at": 60, "settings": { "loss": 0, "flap_period": 0 } }
  ]
}
```

**Nível do arquivo**

| chave | significado |
|---|---|
| `steps` | obrigatória - a lista de etapas. Um simples `[ ... ]` no nível superior também funciona, e significa `loop: false`. |
| `loop` | opcional, padrão `false`. Repete a linha do tempo sem parar, recomeçando depois do `at` da ÚLTIMA etapa. As configurações e a ação da última etapa são aplicadas logo antes de cada reinício, então em um laço ela dura só um instante - para manter uma fase final, adicione uma etapa posterior. |

**"Apply changes" enquanto um cenário roda** - é aplicado na hora, e toda etapa seguinte se constrói
sobre ele, em vez de sobre as configurações que o START deu à sessão. Uma configuração que nenhuma
etapa toca (o processo alvo, o direcionamento de destino) mantém o novo valor até o fim. Uma
configuração que as etapas definem mantém o novo valor só até a próxima etapa, que recoloca o valor
do cenário.

**Nível da etapa** - uma etapa precisa de `settings`, `action` ou ambos. Uma que não tenha nenhum dos
dois é um erro, e não uma pausa.

| chave | significado |
|---|---|
| `at` | obrigatória - segundos desde o início da sessão (`>= 0`). As etapas são ordenadas por ela, então a ordem delas no arquivo não importa. |
| `settings` | um objeto de configurações **parcial**. **Cumulativo**: cada etapa altera o estado deixado pelas anteriores, então um valor permanece até que alguma etapa posterior o mude de volta. |
| `action` | `reset_tcp` - derruba as conexões TCP no escopo naquele momento. **É a única ação.** A grafia `reset_now`, anterior à 1.3, foi removida, então um arquivo que ainda a use falha ao carregar com uma mensagem que nomeia a etapa. |
| `duration` | segundos em que o reset mantém as conexões derrubadas (padrão `3`), maior que 0 e no máximo 3600. Válido somente junto com uma `action`. |

**Quais nomes vão em `settings`** - qualquer configuração que a ferramenta tenha, com o **mesmo nome
do arquivo de configuração** (ou seja, a flag de linha de comando com os hifens trocados por
sublinhados): `loss`, `latency`, `jitter`,
`down`, `up`, `buffer`, `spike_prob`, `flap_period`, `dst_ip`, `block_port`, `target`,
`rate_schedule`, `max_size`, `nat_timeout`, `rst_prob`, `lan_mode`, `internet_only` e as
demais. Execute
`--print-config` para despejar o conjunto completo de nomes com os valores atuais. Uma etapa não
pode alterar `filter`, `duration`, `narrow_filter`, `row_limit` nem `seed`: uma sessão assume os
três primeiros e a `seed` apenas no START, e somente as tabelas da janela leem `row_limit`, nunca o
motor. Uma etapa que defina um deles não muda nada - o arquivo ainda carrega, e avisa isso.

**Tudo é validado quando o arquivo carrega, e um erro se nomeia sozinho.** Uma configuração
desconhecida, uma ação desconhecida, uma chave desconhecida, uma `duration` que não é um número, uma
etapa que não faz nada, uma lista de etapas vazia ou com mais de **1000** etapas - cada uma falha
com uma mensagem apontando para o número da etapa. Isso importa mais do que parece: uma chave com
erro de digitação costumava ser **silenciosa**, então `"duraton"` deixava o reset, sem avisar, no
padrão de 3 segundos e `"lop"` desligava o laço sem avisar, e nos dois casos parecia que a
ferramenta estava ignorando o arquivo.

As etapas são aplicadas por um temporizador que marca **a cada 0,1 s**, então tempos menores que um
segundo são respeitados com mais ou menos essa precisão. O `--dry-run` valida um `--scenario` sem
tocar no driver, o que o torna uma verificação barata em um pipeline.

### Os cenários que acompanham o programa em `scenarios/`

Todos repetem em laço, exceto `upload-drop-midway.json`, então você pode iniciar um e deixá-lo rodando.

| arquivo | o que reproduz |
|---|---|
| `cafe-wifi.json` | Uma cafeteria enchendo ao longo de 85 s: um link razoável se degrada até ~240 ms de ping, 6% de perda e 2 Mbit/s, com a conexão caindo por completo a cada 12 s no pior ponto, e depois se recupera. |
| `mobile-lte-to-3g.json` | Um celular saindo da cobertura LTE: de 33 Mbit/s de download para os 0,8 do 3G, depois uma **queda total com um reset de TCP** aos 60 s, depois uma recuperação parcial e a volta ao LTE. O cenário para testar o que o seu aplicativo faz quando a rede morre no meio de uma requisição. |
| `congested-vpn.json` | Uma VPN cujo **upload** desaba enquanto o download segue bem (512 a 160 KB/s), com picos de latência, um MTU de 1400 e resets ocasionais. |
| `failing-dns.json` | Mira **somente a porta 53** (DNS - para deixar o DNS sobre TCP em paz, defina o Filter como "UDP only" antes do START): a resolução de nomes se degrada até 60% de perda e 1,5 s de ping, fica **100% morta por 13 s** e depois volta. Todo o resto da máquina continua funcionando, e é isso que o torna um teste de DNS, e não de queda total. |
| `overloaded-game-server.json` | Um servidor cedendo sob carga: ping, jitter, perda e duplicação sobem juntos, com picos de latência de até 800 ms em 45% dos pacotes. |
| `same-loss-in-runs.json` | Os mesmos 5% de perda durante toda a execução, chegando de quatro maneiras diferentes: distribuídos uniformemente e depois em rajadas de 5, 15 e 40 pacotes. Mais nada muda, então o que quebrar é a FORMA da perda, e não quanto dela existe. O cenário para descobrir se o seu caminho de reconexão funciona. |
| `upload-drop-midway.json` | **Não repete em laço** - um disparo único: um upload que começa saudável, se degrada, é **cortado a zero no meio da transferência** com um reset de TCP e depois se recupera parcialmente. Para testar uploads retomáveis e barras de progresso que mentem. |
| `blocked-endpoint.json` | Um backend (`203.0.113.0/24`) é **bloqueado** aos 20 s enquanto todo o resto continua funcionando, e depois desbloqueado. Para testar timeouts, novas tentativas e alternativas contra uma única dependência. |

## Receitas de CI/CD

### 1. Degradação do link em segundo plano nos testes E2E (GitHub Actions, Windows)

Os testes rodam com 300 ms de atraso e 5% de perda. O shaper para sozinho depois de 120 s, então
nenhuma etapa "travada" deixa uma rede quebrada no agente.

```yaml
- name: Start the network shaper (background, self-stopping)
  shell: pwsh
  run: |
    $p = Start-Process -FilePath dist\BeanNetworkTester\BeanNetworkTester.exe `
      -ArgumentList '--latency','300','--loss','5','--duration','120',
                    '--dst-port','443','--fail-on-no-traffic',
                    '--format','json','--log-file','shaper.log' `
      -RedirectStandardOutput shaper.ndjson -PassThru
    "SHAPER_PID=$($p.Id)" >> $env:GITHUB_ENV

- name: Run the E2E suite under bad network
  run: npm run test:e2e

- name: Stop the shaper and check it actually impaired something
  if: always()
  shell: pwsh
  run: |
    Stop-Process -Id $env:SHAPER_PID -ErrorAction SilentlyContinue
    Get-Content shaper.ndjson | Select-Object -Last 1
```

> **Observação:** execute o processo em segundo plano com `--duration` - é a rede de segurança. Mesmo
> que a etapa "Stop" nunca rode (cancelamento do job, timeout), a sessão se encerra sozinha, o
> driver é liberado e o agente recupera a sua rede normal.

### 2. Validação de configuração em pre-commit / PR (sem driver, sem administrador)

```bat
BeanNetworkTester.exe --dry-run --config profiles/bad-3g.json
```
O código `0` = o arquivo é válido. `3` = há um erro (com uma mensagem legível no stderr). Uma
configuração com erro de digitação conta como erro e diz qual é a chave - antes ela era descartada
em silêncio, então a verificação passava e a execução saía sem aquela configuração.

O `--dry-run` verifica as **configurações**, e não a máquina: ele nunca pergunta sobre permissões de
administrador nem sobre o driver, então responde `0` em um agente de build que não conseguiria
realmente executar uma captura. Isso é de propósito - validar uma configuração em um lugar e
executá-la em outro é normal. Quando você quiser as duas metades respondidas, execute o par:

```bat
BeanNetworkTester.exe --doctor && BeanNetworkTester.exe --dry-run --config profiles/bad-3g.json
```

### 3. Uma execução curta e repetível com um artefato

```bat
BeanNetworkTester.exe --preset presets.3g --seed 42 --duration 60 ^
  --repro-out repro.json --format json --fail-on-no-traffic > run.ndjson
```
Os artefatos (`run.ndjson`, `repro.json`) bastam para recriar as condições 1:1 - o `repro.json`
contém um `cli_command` pronto.

### 4. Limpando o ambiente do agente

```bat
BeanNetworkTester.exe --doctor
BeanNetworkTester.exe --cleanup-driver
```

## Gerando um .exe

No Windows:

```bat
pip install pyinstaller pydivert psutil
pyinstaller --noconfirm BeanNetworkTester.spec
```

Resultado: **`dist\BeanNetworkTester\BeanNetworkTester.exe`** (um diretório com o exe, o driver
WinDivert, as traduções e o ícone). Esse único arquivo roda **tanto a interface gráfica quanto a CLI**.

Três decisões deliberadas de build (não as mude sem necessidade - cada uma corrige um bug real):

- **subsistema de console** (não `--noconsole`): caso contrário o exe não tem `stdout`/`stderr`, e o
  `cmd.exe` e o PowerShell **não esperam** por um processo gráfico - o CI não veria nem a saída nem o
  código de saída. Ao iniciar a interface gráfica, o programa se desanexa do console sozinho, então
  um clique duplo não deixa uma janela preta.
- **onedir** (não `--onefile`): o `pydivert` carrega o `WinDivert64.sys`, e o onefile o descompactava
  em `%TEMP%\_MEIxxxx`. O kernel mantém um handle aberto para o `.sys` carregado, então o diretório
  **não podia ser excluído** até reiniciar. No build em diretório, o driver fica ao lado do exe, em
  um caminho estável.
- **`asInvoker`** (não `--uac-admin`): o `requireAdministrator` sempre cria um processo **novo** na
  elevação - perdendo os pipes e o código de saída de quem chamou. Agora a própria interface gráfica
  pede a elevação, e a CLI termina com o código `7` e uma mensagem clara quando faltam permissões
  (`--simulate` não precisa delas).

O ícone pode ser regenerado com um script do Pillow (`pip install pillow`), mas o Pillow não é
necessário para o funcionamento normal.

## Pegadinhas (leia antes de abrir um bug)

- **`--duration` é uma rede de segurança, não só uma conveniência.** Sem ele, uma sessão dura até o
  `Ctrl+C` / STOP. No CI, **sempre** passe `--duration`. A única exceção é um cenário com linha do
  tempo: `--scenario` com um arquivo que não repete em laço e tem mais de uma etapa agora encerra a
  execução quando o cenário termina, e avisa isso no início. Um cenário em laço ou de uma etapa só
  não tem um fim onde parar, então avisa e continua até você parar.
- **Fechar a janela do console encerra a execução de forma limpa, sair da sessão do Windows não.**
  Fechar a janela do console termina a execução do jeito que o Ctrl+Break faz: a captura para, o
  resumo é impresso, o relatório de `--repro-out` e o `--log-file` são gravados se você os pediu, o
  driver WinDivert é descarregado, o log diz `Terminated (console window closed).` e o código de
  saída é `143`. O Windows espera apenas cerca de 5 segundos por essa limpeza. Sair da sessão ou
  desligar encerra o programa na hora. O Windows ainda fecha a captura dele, então nenhum tráfego
  continua degradado, mas depois de sair da sessão o driver pode continuar carregado até um
  `--cleanup-driver` ou uma reinicialização.
- **Sem tráfego = uma execução verde.** Se o filtro não pega nem um pacote, o programa funciona
  corretamente e sai com o código `0`. Quer que isso seja um erro? -> `--fail-on-no-traffic`.
- **O filtro de tráfego e a duração só têm efeito a partir do START** (como na interface gráfica):
  "Apply changes" não mexe neles.
- **Depois do STOP, os pacotes que esperam na fila de atraso são descartados.** Com
  `--latency 5000`, podem ser bastantes pacotes de uma vez - isso não é um vazamento, é o fim da
  sessão.
- **O limite de velocidade tem um buffer (`--buffer`, padrão 1000 ms).** Com uma carga oferecida acima
  do limite, quando o buffer enche o excesso vai como "Rate-limit drop" (um contador separado) - é o
  comportamento de um link entupido, não um bug. Aumentar o limite no meio da sessão só tem efeito
  depois que o buffer esvazia (até ~`--buffer` ms). Quer o antigo buffer sem limite (pacotes em vez
  de descartes, ao custo de um atraso crescente)? Defina `--buffer 0`.
- **`--dst-port "!53"` também pega tráfego sem porta** (por exemplo, ICMP): um pacote sem porta "não
  é a porta 53".
- **Um nome de processo puro é uma substring**: `--target chrome` também pega `chromedriver.exe`.
  Para ser preciso: `--target "re:^chrome\.exe$"`.
- **As faixas são inclusivas nos dois extremos** (`80-80` = uma porta), como no nmap/iptables.
- **A CLI está sempre em inglês**, independentemente do idioma da interface e do sistema.
- **O `-q` é realmente silencioso**: em caso de sucesso, não imprime nada. Leia o resultado pelo
  código de saída (ou acrescente `--format json`).
- **Executar sem administrador** (e sem `--simulate`) termina com o código `7` - e não com
  "silêncio".
- **O driver travou um arquivo em `%TEMP%`?** Isso é uma relíquia de builds onefile antigos:
  `BeanNetworkTester.exe --cleanup-driver` o libera sem reiniciar o sistema.

## Testes

O motor é separado do WinDivert, então os testes rodam em qualquer sistema (não precisam de Windows,
de administrador nem de tkinter). A suíte é baseada no **pytest**:

```bat
pip install --require-hashes -r requirements.txt
pip install -r requirements-dev.txt
python -m pytest tests
```

Eles cobrem todos os mecanismos: perda, latência, jitter, limitação por sentido, corrupção,
duplicação, expressões de filtro (listas, faixas, `!`, `>`, `<`, curingas, `re:`, CIDR, IPv6),
direcionamento por processo/destino, descarte de SYN, MTU, oscilação, expiração de NAT, injeção de
RST, picos de latência, o agendamento, o registro de conexões, a repetibilidade (semente), cenários,
o arquivo de configuração, o resumo (PL/EN), as traduções da interface e a reprodução (semente
efetiva, registro de eventos, relatório e comando de CLI). Um teste separado também executa o smoke
da interface gráfica (`smoke_gui.py`, em um tkinter falso), e as convenções do repositório (nomes,
nenhum tkinter no pacote principal, camadas permitidas) são guardadas por testes.

O **contrato de CLI de CI/CD** é guardado separadamente:
- `tests/test_cli_runtime.py` - códigos de saída (0/1/3/4/5/6/130/143), precisão do `--duration` (não
  "até o relatório mais próximo"), separação entre stdout/stderr, NDJSON, `-q`/`-v`, `--dry-run`,
  `--print-config`, `--min-packets`, precedência do `--duration` sobre o arquivo de configuração. O
  laço de relatórios recebe um relógio injetado, então os testes de duração rodam em microssegundos.
- `tests/test_failsafe.py` - a sessão para sozinha depois de `duration`, uma thread de captura morta
  causa um *fail-open* (liberar o driver = a rede volta), o `_tick` da interface gráfica sobrevive a
  uma exceção, a thread de direcionamento nunca toca no tkinter, fechar a janela sempre libera o
  motor.

O **GitHub Actions** executa os mesmos testes a cada push (`.github/workflows/ci.yml`), em uma
matriz Linux + **Windows**: a suíte atrás de um **limite mínimo de cobertura**, o smoke da interface
gráfica no tkinter falso, verificações dos códigos de saída, uma verificação do NDJSON, `--doctor` e
`--license`, e depois **a geração de um `.exe` com um smoke test do arquivo gerado** (`--version`,
`--simulate`, uma configuração inválida -> código 3), além de uma verificação de que o driver
WinDivert realmente foi empacotado ao lado do exe, com um artefato para download.

<!-- ci-jobs:start -->
Todos os jobs desse workflow, e o que significa quando um deles fica vermelho:

| job | o que faz |
|---|---|
| `public-text` | mensagens de commit e a descrição do pull request: em inglês, hifens simples, nada privado de uma máquina |
| `lint` | **ruff**. Código morto, formatos de bug, o teto de complexidade e o teto de argumentos fazem a execução falhar. A família de segurança é reportada e nunca bloqueia |
| `types` | **mypy** sobre o pacote |
| `semgrep` | o conjunto de regras padrão do registro. ERROR, HIGH e CRITICAL fazem a execução falhar, o resto é impresso |
| `mutations` | quebra cada comportamento protegido e prova que o seu teste fica vermelho. Um pull request executa as entradas que tocou, a execução semanal executa todas |
| `audit` | **pip-audit** contra o conjunto fixado. Semanalmente, para perguntar se o mundo se moveu sob versões que não mudaram, e em um pull request que edita um arquivo de requisitos, para perguntar se o conjunto se moveu. A execução semanal abre uma issue, e um pull request que fixa algo vulnerável simplesmente falha |
| `tests` | a suíte, o smoke da interface gráfica, a verificação de renderização com o Tk real e as verificações da CLI, em Linux e Windows |
| `linux-capture` | a captura experimental no Linux em um kernel real: a linha de comando como root, dentro de um namespace de rede próprio. A latência e a perda precisam chegar ao alvo e a nada mais. Não é obrigatório para o merge |
| `build` | o executável do Windows, com smoke test, com a verificação do driver e a varredura do registro de licenças |
| `cron-issue` | abre uma issue quando a execução semanal fica vermelha, sem duplicar conforme os jobs que falharam. Um cron é fácil de passar despercebido e nada mais anuncia um. Também responde a uma execução disparada à mão, que é a única forma de exercitá-lo sem esperar por uma segunda-feira vermelha. Nunca roda em um pull request e nunca fecha uma issue sozinho |
<!-- ci-jobs:end -->

**Três verificações estáticas rodam ao lado dos testes**, somente no Linux, porque leem o
código-fonte em vez de executá-lo. O **ruff** faz um pull request falhar diante de um achado de código
morto ou de formato de bug (`F` e `B`) e reporta a família de segurança (`S`, `ASYNC`) como anotações
que nunca bloqueiam. Duas das regras dele são tetos, e não opiniões: `C90`, para quantos caminhos
existem por uma função, e `PLR0913`, para quantos argumentos ela recebe, ambas fixadas no maior valor
que existe hoje, então ficam em silêncio até que algo cresça além dele. O **mypy** verifica os tipos
do pacote. O **semgrep** varre com o conjunto de regras padrão do registro, e um achado em ERROR,
HIGH ou CRITICAL faz a execução falhar, enquanto tudo abaixo disso é impresso por inteiro. As versões
das três ferramentas são fixadas, então uma nova versão de um linter não consegue deixar vermelho um
pull request que não mudou nada: ruff e mypy em `requirements-lint.txt`, que o CI instala por hashes
exatos de arquivo, e semgrep em `requirements-scan.txt`, fixado apenas por versão. O semgrep é o
único lugar onde uma fixação não consegue prometer uma resposta estável de qualquer modo, porque ele
baixa as suas regras quando roda.

**As dependências são verificadas por três lados.** O job `audit` executa o pip-audit sobre o
conjunto de runtime e de build como instalado. O `review new dependencies`
(`.github/workflows/dependency-review.yml`) faz falhar um pull request que adiciona uma dependência
com um aviso de segurança conhecido ou com uma licença que o projeto não pode distribuir. O
**OSV-Scanner** (`.github/workflows/osv-scanner.yml`) lê cada arquivo de requisitos fixado contra o
banco de dados do OSV: na `master` e a cada semana, ele reporta na aba Security, e em um pull
request só falha quando esse pull request traz um aviso novo.

Há uma etapa que vale conhecer porque nenhum teste unitário consegue fazer o trabalho dela: uma
**verificação de renderização da interface gráfica no Tk real**, sob uma tela virtual, no mínimo
suportado de 1366x768, **em todos os idiomas**. Ela constrói a janela de verdade, percorre cada
página, abre a janela About e faz o build falhar quando algum botão está mais estreito do que pede,
ou seja, quando o texto dele está cortado. Os rótulos em polonês são mais longos que os em inglês,
então é aí que os layouts quebram, e ela já pegou defeitos que eram invisíveis em inglês.

As versões são publicadas por um segundo workflow (`.github/workflows/release.yml`) em uma tag `v*`.
Ele confere a tag com o `VERSION.txt`, se recusa a publicar enquanto os changelogs ainda estão
abertos, compila e faz o smoke test do exe, e abre um **rascunho** com o SBOM em SPDX. Ele
deliberadamente não publica nenhum arquivo compactado: a chave de assinatura fica em um cartão de
hardware que nenhum runner alcança, então o arquivo é assinado na máquina do mantenedor
(`tools/sign_release.py`) e enviado de lá, e um terceiro workflow então atesta os bytes que de fato
são distribuídos.

Uma versão publicada, portanto, traz o zip, o `SHA256SUMS.txt` que este README manda você verificar,
o SBOM e o pacote de atestação. Uma versão completa traz um quinto arquivo, o instalador `.msi`. Uma
versão candidata (release candidate) não traz, porque o Windows Installer ignora o `-rc.1` e trataria
uma candidata e a sua versão final como a mesma versão.

## Estrutura do projeto

O código é dividido no pacote `beantester/`. Um inicializador fino `bean_network_tester.py` fica na
raiz, então todos os comandos existentes (README, relatórios de reprodução, PyInstaller) funcionam
sem mudanças.

```
bean_network_tester.py   inicializador + fachada de compatibilidade (reexporta a API pública)
beantester/              o pacote de implementação
  core.py                núcleo puro de decisão por pacote (BeanCore)
  damage.py              quanto uma sessão degradou: motivos de descarte, parcelas de perda/corrupção
  engine.py              threads de captura/injeção, estatísticas (BeanEngine)
  connlog.py             o registro de conexões da sessão: uma linha por fluxo, e o seu limite
  driverwait.py          quanto os pacotes esperaram na fila do driver antes de a ferramenta recebê-los
  matchers.py            expressões de filtro (lista/faixa/!/>/</curinga/re:) - compartilhadas
                         pelos campos de processo, IP e porta - uma única fonte da verdade
  settings.py            modelo de configurações, arquivo de configuração, apply_settings
  scenario.py  presets.py  filters.py  summary.py  repro.py  views.py
  cli.py                 parser de argumentos, modo CLI e o despachante GUI/CLI
  exitcodes.py           CÓDIGOS DE SAÍDA - o contrato da CLI/CI-CD (única fonte da verdade)
  clilog.py              saída da CLI: log no stderr ([bean]), dados no stdout (texto/NDJSON)
  winenv.py              Windows: administrador, elevação (UAC), desanexar do console, DPI
  driver.py              ciclo de vida do driver WinDivert + --doctor / --cleanup-driver
  fields.py              REGISTRO DE CAMPOS - única fonte da verdade: tipo, rótulo, unidade,
                         faixa, seção do formulário, escopo do perfil, flag da CLI
  validators.py          validação de números e faixas (compartilhada por GUI, CLI e arquivo de configuração)
  portmap.py             tabela de sockets: porta local -> PID (iphlpapi/ctypes, alternativa com psutil),
                         e todos os sockets com o seu estado para a aba Tools
  adapters.py            adaptadores de rede e a rota de saída (iphlpapi/ctypes), para a aba Tools
  proxy.py               o proxy que esta conta e esta máquina usam (winhttp/ctypes e o
                         registro), somente leitura, para a aba Tools
  tcpreset.py            reseta uma conexão TCP (iphlpapi/ctypes), para o menu de linha da
                         página Connections
  targeting.py           conjunto vivo de portas do alvo: árvore de processos, pede reconstrução em caso de falha
  target_resolver.py     reconstrói esse conjunto de portas em uma thread própria, fora do caminho dos pacotes
  socketwatch.py         porta local -> PID ao vivo a partir de eventos SOCKET do WinDivert (fonte orientada a eventos)
  jsonfile.py            gravação atômica + quarentena de arquivos do usuário corrompidos
  crashlog.py            registro de falhas: quiet/note/once, quarentena, relatório em segundo plano
  appinfo.py             identidade do app e leitor de versão (uma só fonte: VERSION.txt)
  i18n.py  paths.py  utils.py  processes.py  synthetic.py  legal.py  scenario_runner.py
  nettools/              a lógica por trás da aba Tools, um módulo por ferramenta - sem tkinter,
                         então é testada sem janela
  gui/                   a interface tkinter
    app.py               composição da janela, estado, start/stop, estado alterado
    logview.py           a caixa de log: a sua fila, o seu buffer de linhas e o seu widget
    form.py              formulário gerado a partir de fields.FIELD_DEFS
    form_search.py       comparação de uma busca digitada com o registro de campos (pura)
    scaling.py           DPI, pixels escalados, geometria de janela/gráfico/dica
    wheel.py             normalização da roda do mouse (uma função pura)
    scrollable.py        ScrollableFrame + UM despachante global da roda
    accordion.py         seções recolhíveis
    ui_state.py          persistência do estado da janela (bean_network_tester_ui.json)
    prefs.py             preferências da GUI (idioma, gráfico, log) guardadas em ui.json
    pages/               registro de páginas: control, stats (3 subabas), conns, toolbox (Tools)
    toolbox/             a aba Tools: o seu registro de ferramentas e um painel por ferramenta
    field_actions.py     preencher um campo da página Control a partir de outro lugar (menus de linha das tabelas, aba Tools)
    clipboard.py         copiar um texto inteiro, confirmado relendo a área de transferência
    links.py             os botões Donate e GitHub - o único código que abre uma página web
    configure.py         configurar um widget só com as opções que realmente mudam
    panels/              janelas secundárias: "About", "Settings" e o registro de eventos destacado
    widgets/             SortableTree (ordenação, diff de linhas, Ctrl+C, limite de largura de coluna, menu de linha)
    model_worker.py      reconstrói o modelo de uma tabela em uma thread de trabalho (a UI nunca trava)
    windows.py           classe base e registro das janelas secundárias
    dialogs.py           substitutos escuros, dentro do app, para messagebox/simpledialog
    rates.py             média de vazão e pico de cada visão (pura, testável)
    scope.py             o que os números na tela cobrem (um veredito puro)
    crash.py             o que a GUI informa ao registro de falhas: contexto do relatório, breadcrumb
    csv_export.py        as duas exportações CSV e os nomes de coluna que elas gravam
    session_repro.py     com o que a sessão rodou: o relatório de reprodução e "Copy CLI command"
    applied.py           com o que "Apply changes" compara o formulário (um auxiliar puro)
    theme.py  chart.py  tooltip.py  profiles.py  icon.py  labels.py
lang/                    traduções (en, pl, zh)
tests/                   testes pytest
smoke_gui.py             smoke da GUI em um tkinter falso
BeanNetworkTester.spec   a receita de build (onedir, console, asInvoker)
```

## Como funciona (em resumo)

O núcleo `BeanCore.decide()` é uma função pura que decide, em ordem, o destino de um pacote:
direcionamento -> modo LAN -> bloqueio (firewall) -> NAT -> RST -> oscilação -> MTU -> SYN -> perda -> corrupção ->
atraso/jitter/pico -> limite de vazão (um token bucket com um buffer limitado, opcionalmente vindo do
agendamento) -> duplicação. A thread de captura lê os pacotes e executa a decisão. A thread de
reinjeção os envia no momento escolhido. Toda a aleatoriedade passa por um único gerador (opcionalmente
com semente).

## Observações e limitações

- Ele modifica o tráfego que combina com o filtro. Para testes mais restritos, use "Target process" ou
  "Target destination".
- Ping = ICMP: para afetá-lo, escolha um filtro que inclua ICMP.
- Um limite de velocidade é difícil de ver no ping (pacotes pequenos) - teste com o download de um
  arquivo.
- A captura e a injeção reais de RST só funcionam no Windows com o WinDivert. A lógica é confirmada
  por testes que rodam em qualquer lugar.
- Uma ferramenta para testar os seus próprios aplicativos e redes.

### Comportamentos que vale conhecer

- **O agendamento se repete em laço** - depois da última etapa, volta à primeira (`2:100:0, 2:500:0`
  alterna 2 s a 100 KB/s e 2 s a 500 KB/s, sem parar). Aplicar um agendamento alterado no meio da
  sessão recomeça o ciclo pela primeira etapa. Aplicar o mesmo de novo, ou mudar qualquer outra
  configuração, deixa o ciclo onde está.
- **O agendamento tem precedência sobre um limite fixo** - quando o campo "Schedule" não está vazio,
  os valores de "Download/Upload" (KB/s) são ignorados, porque a vazão vem das etapas do
  agendamento.
- **O agendamento é opcional, mas precisa ser válido** - um campo vazio = sem agendamento, enquanto
  uma entrada ruim (por exemplo, `1:100`, `2:abc:0`) é reportada como erro: a interface gráfica não
  inicia a sessão e a CLI termina com uma mensagem. Nada é ignorado em silêncio.
- **As expressões de filtro são validadas** - uma entrada inválida no campo de processo/IP/porta (por
  exemplo, `999.1.1.1`, `2000-1000`, `>chrome`, `re:[`) é reportada como erro em vez de não fazer
  nada em silêncio: na interface gráfica, o campo fica vermelho com o motivo abaixo dele, e a CLI
  termina com uma mensagem `error: ...`. A comparação de endereços não depende da notação (uma forma
  curta e uma forma completa de IPv6 são o mesmo endereço).
- **Os positivos se somam, as exclusões subtraem** - `80,443,!8080` significa "80 ou 443, mas não
  8080", e `!53` sozinho significa "tudo, exceto 53". A ordem dos termos não importa. Detalhes e casos
  de borda: [Sintaxe de filtros](#sintaxe-de-filtros-processo--ip--porta).
- **As faixas são inclusivas nos dois extremos** - `8000-8100` cobre 8000 e 8100 (como no
  nmap/iptables), e `80-80` é exatamente uma porta.
- **IP e porta em "Target destination" se combinam com AND** - definir os dois campos restringe ao
  tráfego que satisfaz **as duas** condições ao mesmo tempo.
- **Um limite de velocidade muito baixo = perda real** - com o buffer padrão (1000 ms), o excesso
  acima do limite é descartado quando o buffer enche e contado na estatística **"Rate-limit drop"**
  (um contador separado, não "Loss") - é assim que um link congestionado se comporta, então a perda
  efetiva pode então ser maior que a porcentagem de "Loss" configurada. Somente com `--buffer 0` (um
  buffer sem limite) a fila da ferramenta cresce até o seu teto rígido de **20 000** pacotes, e aí o
  excesso é contado como **"Buffer overflow"**.
- **Um campo Seed vazio = uma semente aleatória** - o programa ainda sorteia um valor concreto e o
  mostra no painel da sessão. Nos arquivos de configuração, o valor `-1` significa "sortear", então o
  `-1` não pode ser usado como uma semente comum (qualquer outro número, inclusive um negativo,
  funciona normalmente).
- **O direcionamento por processo inclui processos filhos** - um socket pertence ao alvo se o
  processo **que o abriu, ou qualquer um dos seus ancestrais**, combina. É por isso que o
  `chrome.exe` (ou o PID da janela do navegador) também pega o processo de rede dele - que é o que
  mantém todas as conexões. Uma exclusão explícita vence: `chrome, !chromedriver` não puxa o
  `chromedriver` por meio de um processo pai.
- **O direcionamento por processo é guiado por eventos de socket, não por uma sondagem lenta.** O
  WinDivert nos entrega um pacote, não um PID, então associamos um pacote ao seu processo pela
  **porta local**. No Windows, a ferramenta observa os eventos de socket do sistema (connect / bind /
  accept / close) conforme acontecem, então uma nova conexão **ou fluxo UDP** de um programa que **já**
  está no escopo é degradada desde o seu primeiríssimo pacote - isso cobre consultas DNS e QUIC, cada
  um dos quais usa uma porta nova. A exceção é a *primeira* conexão do programa: até que ele possua
  pelo menos um socket, não há nada pelo qual reconhecê-lo, então essa conexão passa intacta. Sem o
  WinDivert de verdade (o caminho de teste / simulação), recorre a examinar a tabela de sockets
  algumas vezes por segundo, em que o primeiro pacote de qualquer conexão novinha em folha pode
  escapar. De um jeito ou de outro, a observação roda em uma thread própria, nunca na que cuida dos
  seus pacotes, então nunca pode virar tráfego perdido.
- **Se o programa em teste reiniciar, mire pelo NOME, não pelo id do processo.** Medido: um alvo que
  sai e volta com um novo id de processo é retomado sozinho, e a reinicialização custa exatamente uma
  conexão - a que ele abre antes de possuir qualquer socket. Mirar em um **id de processo** nunca se
  recupera, porque esse id nomeava o processo que saiu: tudo depois da reinicialização fica intacto.
  Um programa a quem o Windows der depois o mesmo número também fica intacto - um id de processo só
  significa o processo que o tinha quando você definiu o alvo.
  Pela linha de comando, a execução avisa quando isso acontece e termina com quanto do tráfego
  capturado estava de fato no escopo. Na janela, é a nota vermelha sob o campo de processo.
- **Uma exclusão sozinha também cobre tudo o que a ferramenta não consegue identificar.** `!chrome`
  no campo de processo significa "degrade tudo, exceto o chrome" - e "tudo" inclui qualquer conexão
  cujo processo dono não pôde ser determinado: processos protegidos do sistema que a ferramenta não
  consegue abrir e, na alternativa por sondagem, os primeiros pacotes de um socket novinho em folha.
  **Portanto, não use uma exclusão para proteger um aplicativo.** Se você quer um aplicativo em paz,
  nomeie o aplicativo que você QUER quebrar (`--target thatapp`) - assim tudo o que não foi
  identificado passa intacto, que é o sentido seguro. Isso espelha o `!53` nas portas, abaixo.
- **Um direcionamento que não pega nada não quebra nada** - se nenhum processo correspondente tem uma
  conexão aberta, o tráfego passa intacto. Isso cobre um programa que não está rodando e um que está
  rodando, mas ocioso. Quando esse programa abre uma conexão, a ferramenta a adiciona em
  milissegundos, então os primeiros pacotes dessa conexão podem passar intactos e o resto é
  degradado. O programa avisa isso explicitamente (uma nota vermelha sob o campo e uma entrada no
  log), porque "uma execução em que nada quebrou" tem a mesma aparência de "o aplicativo aguentou".
- **Um nome de processo puro é uma substring** - `chrome` também pega `chromedriver.exe`. Isso é
  mantido de propósito (compatibilidade com configurações antigas). Para precisão, use
  `re:^chrome\.exe$` ou a exclusão `chrome, !chromedriver`.
- **Um alvo que nomeia todos os programas não restringe nada** - `*.exe`, `exe` ou `*` combinam com
  quase todos os processos que têm uma conexão, então uma execução assim recebe o mesmo aviso de
  partida que uma execução sem alvo nenhum.
- **Statistics e Connections mostram TODO o tráfego capturado por padrão** - o que quer que o filtro
  "Traffic to modify" deixe passar. O direcionamento (processo / IP / porta) decide apenas **o que é
  quebrado**, e não o que fica visível nas tabelas e nos contadores. Duas chaves em Settings, no
  cartão **"Scope"**, mudam isso, e não são a mesma coisa:
  - **"Show only the targeted traffic"** restringe os contadores, o gráfico de vazão, a tabela
    Connections e o CSV de conexões ao que o seu direcionamento selecionou. Ela muda o que você
    VÊ - nunca o que é capturado, nunca o que é degradado, e você pode alterná-la a qualquer
    momento.
  - **"Capture only the targeted traffic"** restringe a *própria captura*: o driver deixa de
    entregar qualquer coisa que não seja o tráfego do seu destino, então as abas cobrem esse tráfego
    porque não há mais nada para cobrir. Ela é fixada quando a sessão começa e só funciona para um
    destino que a linguagem de filtro do driver consegue expressar - um endereço simples, uma lista,
    uma faixa ou um CIDR. Um curinga, um padrão `re:` ou direcionar apenas um processo não podem ser
    empurrados para baixo, e aí a opção não faz nada. O cartão Scope diz qual das duas você está
    obtendo **antes** de você pressionar START, o log diz de novo na partida, e a linha **"Capture"**
    do painel Session a registra para a execução.

  Qualquer uma que esteja ligada, **a nota acima dos contadores e acima da tabela Connections diz o
  que esses números de fato cobrem**, inclusive o caso em que a captura é restrita *e* um alvo de
  processo está definido - a ferramenta então captura o tráfego do seu destino de todos os processos
  e degrada a parte de um processo, então os contadores cobrem mais do que a degradação.
  **Três contadores continuam no tráfego total mesmo com "Show only" ligado**: "Queue overflow",
  "Dropped at stop" e "Send failed" contam pacotes que *esta ferramenta* perdeu, inclusive tráfego
  que você nunca direcionou, e escondê-los esconderia o dano da própria ferramenta. O CSV de
  estatísticas também não respeita a chave "Show only" - é um registro de acréscimo, então carrega os
  dois totais em colunas separadas - mas registra "Capture only" por linha em `capture_narrowed`,
  porque essa muda o que foi contado, afinal. O relatório de reprodução e o `--format json` sempre
  carregam os dois números.
- **O limite de velocidade modela a MÉDIA** - o token bucket deixa passar rajadas curtas, então o
  "Download/Upload peak" (a média em uma janela de 1 s) pode ficar um pouco acima do limite definido.
  Os duplicados contam contra o limite (a segunda cópia também trafega pelo link).
- **A janela tem um tamanho máximo e não pode ser maximizada** - o layout (duas colunas + a barra de
  log) deixa de fazer sentido esticado para 4K, então o tamanho tem um teto e o botão de maximizar
  foi removido.
- **A duração conta a partir do START** - mudar o campo no meio da sessão não faz nada (como o filtro
  de tráfego). Quando o limite é atingido, o programa simplesmente dá STOP e deixa os resultados na
  tela.
- **O STOP descarta os pacotes que esperam na fila de atraso** - o fim de uma sessão é imediato. Com
  uma `latency` grande, isso aparece como uma "lacuna" isolada. Não é um bug.
- **Uma falha no meio da sessão sempre termina com a rede restaurada** - se a thread de captura ou de
  injeção morre, ou para de avançar por 10 segundos, o motor dá STOP sozinho e libera o driver
  (*fail-open*), em vez de segurar um handle aberto que ninguém alcança (esse era um caminho real
  para "o usuário de repente fica sem internet"). O motivo vai para o log e para o registro de
  eventos. Uma thread que continua presa depois do STOP é deixada para trás em vez de esperada, e o
  próximo START avisa isso no log.
- **Fechar o programa libera o driver WinDivert** - não depois de cada sessão (reiniciar uma sessão
  deve ser instantâneo), mas **uma vez, na saída**. Enquanto o driver está carregado, o kernel mantém
  aberto o `WinDivert64.sys` que fica ao lado do exe - e então **o diretório do programa não pode ser
  removido, mesmo quando parece vazio** (o Windows deixa você excluir um arquivo com um handle
  aberto: ele some da lista, mas fica em *pending delete* e bloqueia o diretório). Se algo sobrar, o
  resgate sem reiniciar é `BeanNetworkTester.exe --cleanup-driver` (ou `sc stop
  WinDivert` + `sc delete WinDivert`). Na saída, o programa mexe apenas no serviço `WinDivert` que
  ele carrega, e o deixa carregado enquanto outra cópia deste programa o estiver usando. O
  `--cleanup-driver` também para o `WinDivert1.4` e o `WinDivert1.1`, que outros programas instalam.
- **"Duration" e "Traffic to modify" são considerados apenas no START** - e é por isso que durante uma
  sessão os dois ficam **travados** (um campo editável que não faz nada é pior que um esmaecido).

## Como contribuir

Contribuições são bem-vindas. O [CONTRIBUTING.md](CONTRIBUTING.md) explica como configurar os testes
e as convenções que o projeto segue. Leia também o
[Código de Conduta](CODE_OF_CONDUCT.md). Relatos de bugs e pedidos de recursos passam pelos modelos
de issue, e as questões de segurança são tratadas em privado por meio da [política de
segurança](SECURITY.md).

## Apoie o projeto

O projeto é desenvolvido por **DonislawDev** e é gratuito. Se a ferramenta economiza o seu tempo e
você quer que mais recursos apareçam, você pode apoiar **voluntariamente** o desenvolvimento dela:

**https://donislawdev.com/support/**

O apoio é totalmente opcional - todas as funcionalidades funcionam sem ele. No programa, o botão
**Donate** leva até lá (o cabeçalho da janela e a janela About). O botão **GitHub** ao lado dele abre
a página deste projeto.

## Autor

**DonislawDev** - https://donislawdev.com/

O Bean Network Tester é construído com um fluxo de trabalho assistido por IA.

## Licença

O Bean Network Tester é um **software livre e de código aberto**, licenciado sob a **GNU General Public
License, versão 3 (GPLv3)** - veja o arquivo [LICENSE](LICENSE).

Em resumo: você é livre para usá-lo para qualquer finalidade (particular ou comercial), para estudar
como ele funciona e alterá-lo, e para redistribuir cópias - inclusive modificadas - desde que
repasse o programa sob os mesmos termos da GPLv3 e disponibilize o código-fonte correspondente. O
programa é fornecido "COMO ESTÁ" ("AS IS"), sem garantia e sem responsabilidade por parte do autor.
O autor é **DonislawDev**.

### Marcas registradas e os números dos perfis

Ookla, Speedtest, Starlink, HughesNet e Viasat são marcas registradas dos seus respectivos
proprietários. Elas são citadas neste projeto por um único motivo: dizer de **quem são as medições
publicadas** de onde vieram os números de um perfil. O Bean Network Tester não é afiliado,
endossado nem patrocinado por nenhuma delas, e nenhum dado delas é redistribuído aqui - apenas
números individuais, citados com a fonte, como qualquer documento técnico cita um.

### O que você produz com ele é seu

**A GPL cobre o programa, não a sua saída.** Os arquivos de cenário que você escreve, os perfis e
arquivos de configuração salvos, os relatórios de reprodução, os CSVs exportados, os arquivos de log
e as capturas de tela são trabalho seu. Usar o Bean Network Tester não os coloca sob a GPL e não o
obriga a publicar nada. Mantenha-os privados, distribua-os com um produto de código fechado, venda-os
- a decisão é sua.

Uma coisa que convém manter separada: os cenários de exemplo que vêm **com** o programa, no diretório
`scenarios/`, fazem parte do projeto e são GPLv3 como o resto dele. Um cenário que você mesmo
escreve não é, mesmo que você tenha partido de um deles e mudado os números.

## Componentes de terceiros

O programa usa bibliotecas de outros autores, sob as respectivas licenças - entre elas
**[WinDivert](https://www.reqrypt.org/windivert.html)** e
**[PyDivert](https://github.com/ffalcinelli/pydivert)** sob a **LGPLv3**,
**[psutil](https://github.com/giampaolo/psutil)** (BSD), **[CPython](https://www.python.org/)** (PSF),
**[Tcl/Tk](https://www.tcl-lang.org/)** e o bootloader do **[PyInstaller](https://pyinstaller.org/)**.
A lista completa, as versões e os endereços do código-fonte estão em
[THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md), e os textos completos das licenças estão no
diretório `licenses/`. De dentro do programa: `--license` (CLI) ou o botão **About** na interface.

As bibliotecas LGPL podem ser substituídas por versões suas, compatíveis com a interface, e as duas
são substituídas de maneiras diferentes. O **WinDivert** é uma DLL e um driver carregados do disco
em tempo de execução, então você troca os arquivos em `_internal\pydivert\windivert_dll\` - e é por
isso que o programa é gerado como **onedir** e não como um arquivo único. O **PyDivert** é Python
puro e é compilado dentro do .exe, então é substituído recompilando o programa contra a sua versão,
ou executando-o a partir do código-fonte. Colocar uma cópia modificada ao lado do .exe não funciona,
e o [THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md) diz isso em vez de deixar você descobrir sozinho.
A GPLv3 é compatível com as licenças desses componentes, e nada na licença do projeto restringe os
direitos que decorrem delas.

## Privacidade: sem telemetria

O Bean Network Tester **não envia nada por conta própria**. Não tem telemetria, nem verificação de
atualizações, nem serviços externos. A ferramenta captura o tráfego de rede no seu computador - e
esses dados **nunca saem dele**. Só duas coisas saem, e só quando você pede: uma página aberta no seu
navegador - a página de apoio ou a página do projeto no GitHub - quando você mesmo clica no botão
correspondente, e as solicitações de eco da ferramenta **Ping** da aba Tools, que vão só para o
endereço que você digita, de Start a Stop. Se você digitar um nome em vez de um endereço, o Windows
o consulta primeiro, como para qualquer programa.

## Uma observação sobre o SmartScreen e o antivírus

**A partir da 0.5.0, o .exe é assinado**, com um certificado cuja chave privada fica em um cartão de
hardware que nunca sai da mesa do mantenedor - assim o Windows nomeia o editor em vez de dizer
"Editor desconhecido" ("Unknown publisher"). Saiba o que isso garante e o que não garante: um
certificado novo ainda não tem reputação no SmartScreen, então um aviso ainda pode aparecer por
algum tempo, e algumas ferramentas antivírus ainda podem disparar um falso alarme sobre um programa
que pede permissões de administrador e carrega um driver de rede. O que muda é que o aviso agora diz
quem assinou. O **próprio driver WinDivert é assinado digitalmente pelo seu autor**. Você ainda pode
comparar o checksum SHA-256 da versão (`SHA256SUMS.txt`) para confirmar que o arquivo chegou sem
alterações.

**Você também pode verificar o que o download contém, e não só que ele não foi alterado.** Cada
arquivo compactado de uma versão carrega uma declaração assinada que lista tudo o que há dentro dele,
feita pelo próprio workflow deste repositório sobre os bytes exatos que você baixou:

```bash
gh attestation verify BeanNetworkTester-v0.5.0-windows-x64.zip -R donislawdev/BeanNetworkTester --predicate-type https://spdx.dev/Document/v2.3
```

Um checksum prova que o arquivo corresponde ao que a página da versão diz. Isto prova que a lista de
materiais ao lado descreve esses mesmos bytes, e que a declaração foi feita por um workflow deste
repositório e não por quem lhe entregou o arquivo.

O `--predicate-type` não é opcional. Sem ele, o `gh` procura uma declaração de proveniência de build
e responde `HTTP 404`, porque o arquivo compactado que você baixa foi **assinado na máquina do
mantenedor**, e não construído em um runner - a chave de assinatura está em um cartão que nenhum
runner alcança. A proveniência é atestada para o build sem assinatura dentro do workflow. O que
viaja com a versão é a lista de materiais sobre o arquivo assinado.

Esse comando pergunta ao GitHub quais atestações existem. A prova também acompanha **como um
arquivo**, o `BeanNetworkTester-vX.Y.Z.sigstore.json`, para que você possa conferir o arquivo
compactado contra uma evidência que viajou junto com ele:

```bash
gh attestation verify BeanNetworkTester-v0.5.0-windows-x64.zip --bundle BeanNetworkTester-v0.5.0.sigstore.json --repo donislawdev/BeanNetworkTester --predicate-type https://spdx.dev/Document/v2.3
```

As duas flags extras são necessárias e nenhuma é enfeite. O `--repo` nomeia o repositório com o qual a
identidade de assinatura precisa coincidir. O `--predicate-type` está ali porque este pacote (bundle)
é a atestação do **SBOM**, e o `gh` procura uma de proveniência de build a não ser que você diga o
contrário - sem ele você recebe "no attestations found with predicate type", que é a ferramenta sendo
precisa, e não quebrada. Quando o arquivo está bom, ele não imprime nada e sai com 0. Altere um byte
e ele sai com 1.

São três declarações, e vale saber que elas respondem a perguntas diferentes. A **assinatura** diz
quem responde pelo arquivo. O **pacote (bundle) acima** vincula este arquivo compactado exato à sua
lista de materiais, e é feito depois da assinatura, sobre os bytes que você baixou. A **proveniência
de build** diz qual commit e qual workflow produziram o build que foi então assinado - ela
necessariamente descreve o build sem assinatura, porque assinar muda os bytes, e fica no repositório
de atestações deste repositório, e não no download.

### O que há dentro do download e como verificar

Cada versão carrega um **SBOM** - uma lista, no formato padrão SPDX, de cada componente de terceiros
do build com a sua versão, licença e o local do seu código-fonte. É a mesma lista que
`BeanNetworkTester.exe --license` imprime, em uma forma que uma ferramenta consegue ler.

O SBOM é **assinado contra o arquivo compactado que ele descreve**, então os dois não podem ser
separados:

```bash
gh attestation verify BeanNetworkTester-vX.Y.Z-windows-x64.zip --repo donislawdev/BeanNetworkTester --predicate-type https://spdx.dev/Document/v2.3
```

Um checksum diz que o arquivo chegou sem alterações. A atestação diz que *esta* lista de materiais
pertence a *este* arquivo compactado, e que a declaração foi feita pelo workflow de release deste
repositório. Deixe o `--predicate-type` de fora e o `gh` procura uma declaração de proveniência de
build e responde `HTTP 404`.
