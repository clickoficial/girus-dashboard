# 🚀 Como colocar o Dashboard no Railway
## Feito uma vez — depois atualiza sozinho para sempre

---

## O QUE VOCÊ VAI PRECISAR
- Conta no GitHub (gratuita) → github.com
- Conta no Railway (gratuita) → railway.app
- app_key e app_secret do Omie
- 15 minutos

---

## PASSO 1 — Subir os arquivos no GitHub

1. Acesse **github.com** e faça login (ou crie uma conta)
2. Clique em **"New repository"**
3. Nome: `girus-dashboard`
4. Marque **Private** (importante — repositório privado)
5. Clique **"Create repository"**

Agora faça upload dos arquivos:
6. Clique em **"uploading an existing file"**
7. Faça upload de TODOS os arquivos da pasta `girus-dashboard`:
   - `server.py`
   - `requirements.txt`
   - `Procfile`
   - Pasta `static/` com o `index.html` dentro
8. Clique **"Commit changes"**

---

## PASSO 2 — Criar o projeto no Railway

1. Acesse **railway.app** e faça login com sua conta GitHub
2. Clique em **"New Project"**
3. Escolha **"Deploy from GitHub repo"**
4. Selecione o repositório `girus-dashboard`
5. Railway detecta automaticamente que é Python e inicia o deploy

---

## PASSO 3 — Configurar as credenciais (PARTE MAIS IMPORTANTE)

As credenciais ficam AQUI — nunca no código.

1. No Railway, clique no seu projeto
2. Vá em **"Variables"**
3. Adicione uma por uma:

| Nome da variável | Valor |
|---|---|
| `OMIE_APP_KEY` | sua app_key do Omie |
| `OMIE_APP_SECRET` | seu app_secret do Omie |
| `DASH_USER` | `girus` (ou o usuário que quiser) |
| `DASH_PASS` | uma senha forte (ex: `Girus@2026!`) |

4. Clique **"Deploy"** após adicionar as variáveis

---

## PASSO 4 — Gerar o link público com senha

1. No Railway, vá em **"Settings"**
2. Em **"Networking"** → clique em **"Generate Domain"**
3. Seu link será algo como: `https://girus-dashboard.up.railway.app`

---

## PASSO 5 — Testar

1. Acesse o link gerado
2. O navegador vai pedir **usuário e senha**
3. Entre com o DASH_USER e DASH_PASS que você definiu
4. O dashboard vai aparecer conectando ao Omie

Na primeira vez pode demorar 1-2 minutos para carregar enquanto busca os dados.

---

## RESULTADO FINAL

✅ Link seguro com senha
✅ Credenciais Omie nunca expostas
✅ Atualiza sozinho a cada 1 hora
✅ Abre em qualquer TV, celular ou computador
✅ Grátis no plano Railway Hobby ($5/mês se precisar de mais recursos)

---

## DÚVIDAS COMUNS

**O dashboard ficou em branco / carregando para sempre**
→ Verifique se as variáveis OMIE_APP_KEY e OMIE_APP_SECRET estão corretas no Railway

**Esqueci a senha**
→ Mude o DASH_PASS nas variáveis do Railway e faça redeploy

**Quero mudar a previsão mensal de custos**
→ Fale com o assistente que gerou este projeto — ele atualiza os valores em segundos
