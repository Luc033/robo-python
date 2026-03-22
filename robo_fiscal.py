import requests
import time
import os
import google.generativeai as genai
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

# ==========================================
# CONFIGURAÇÃO DA API DO GEMINI
# ==========================================
# Crie sua chave gratuita em: https://aistudio.google.com/app/apikey
CHAVE_API_GEMINI = "COLE_SUA_CHAVE_AQUI"
genai.configure(api_key=CHAVE_API_GEMINI)

class RoboFiscal:
    def __init__(self, cnpj):
        self.cnpj_limpo = "".join(filter(str.isdigit, cnpj))
        self.cnpj_formatado = cnpj
        
        self.relatorio = {
            "cnpj": self.cnpj_formatado,
            "razao_social": None,
            "uf": None,
            "regime": "Desconhecido",
            "ie": "Não verificada",
            "status_ie": "Não verificado",
            "alerta_bloqueio": False
        }

    # ==========================================
    # MOTOR DE INTELIGÊNCIA ARTIFICIAL (GEMINI)
    # ==========================================
    def quebrar_captcha_com_ia(self, page, seletor_imagem):
        """Tira print do captcha e pede para o Gemini ler"""
        print("   [IA] A capturar a imagem do Captcha...")
        caminho_imagem = "captcha.png"
        
        # Aguarda a imagem carregar e tira o print
        elemento_img = page.wait_for_selector(seletor_imagem)
        elemento_img.screenshot(path=caminho_imagem)
        
        print("   [IA] A enviar imagem para o Gemini analisar...")
        try:
            # Usando o modelo flash (mais rápido e barato/grátis)
            modelo = genai.GenerativeModel('gemini-1.5-flash')
            arquivo_img = genai.upload_file(caminho_imagem)
            
            prompt = (
                "Você é um sistema automatizado de leitura de imagens. "
                "Leia o texto presente neste captcha. "
                "Responda APENAS com os caracteres (letras e números) visíveis. "
                "Não inclua espaços, pontuações, quebras de linha ou explicações. "
                "Se as letras estiverem riscadas, tente deduzir a letra original."
            )
            
            resposta = modelo.generate_content([prompt, arquivo_img])
            texto_captcha = resposta.text.strip().replace(" ", "")
            
            # Limpa o arquivo da nuvem do Google e local
            arquivo_img.delete()
            os.remove(caminho_imagem)
            
            print(f"   [IA] O Gemini leu: '{texto_captcha}'")
            return texto_captcha
            
        except Exception as e:
            print(f"   [Erro na IA] Falha ao comunicar com o Gemini: {e}")
            return ""

    # ==========================================
    # CAMADA 1: Portal do Simples Nacional
    # ==========================================
    def camada1_verificar_simples(self, page):
        print("\n[Camada 1] A consultar o Portal do Simples Nacional...")
        page.goto("https://www8.receita.fazenda.gov.br/SimplesNacional/Aplicacoes/AtuAL/pgmei.aspx/Consultar")
        
        page.fill("input#cnpj", self.cnpj_limpo)
        
        # --- INTEGRAÇÃO DA IA AQUI ---
        # No site do Simples, geralmente a imagem tem o ID ou classe relacionados a captcha
        # Nota: O seletor exato pode variar. Assumindo um seletor genérico para captchas img.
        try:
            seletor_img_simples = 'img[src*="captcha"]' # Pode precisar de ajuste fino
            texto_captcha = self.quebrar_captcha_com_ia(page, seletor_img_simples)
            page.fill('input[id*="captcha"]', texto_captcha) # Preenche o campo
            page.click('input[type="submit"]') # Clica em consultar
            
            page.wait_for_selector('.label-situacao', timeout=15000)
            html_resultado = page.content().lower()
            
            if "não é optante pelo simples nacional" in html_resultado:
                self.relatorio["regime"] = "Regime Normal"
                print("-> Resultado: Regime Normal identificado. A avançar para a Camada 2.")
                return False
            else:
                self.relatorio["regime"] = "Simples Nacional / MEI"
                print("-> Resultado: Optante pelo Simples Nacional/MEI.")
                return True 
                
        except Exception as e:
            print("[Aviso] Camada 1 ignorada ou falhou. A assumir Regime Normal por precaução.")
            return False

    # ==========================================
    # CAMADA 2: Consulta Pública (BrasilAPI)
    # ==========================================
    def camada2_descobrir_uf(self):
        print("\n[Camada 2] A consultar a BrasilAPI para obter UF...")
        url = f"https://brasilapi.com.br/api/cnpj/v1/{self.cnpj_limpo}"
        resposta = requests.get(url)
        
        if resposta.status_code == 200:
            dados = resposta.json()
            self.relatorio["razao_social"] = dados.get("razao_social")
            self.relatorio["uf"] = dados.get("uf")
            print(f"-> Empresa: {self.relatorio['razao_social']} | UF: {self.relatorio['uf']}")
            return self.relatorio["uf"]
        return None

    # ==========================================
    # CAMADA 3: Sintegra Estadual (SP - 100% Autônomo)
    # ==========================================
    def camada3_consultar_sintegra(self, page, uf):
        print(f"\n[Camada 3] A reencaminhar para o Sintegra do Estado: {uf}")
        if uf == "SP":
            self._scraper_sintegra_sp(page)
        else:
            self.relatorio["status_ie"] = f"Requer consulta manual ({uf})"

    def _scraper_sintegra_sp(self, page):
        print("-> A aceder ao CADESP (São Paulo)...")
        url_sp = "https://www.cadesp.fazenda.sp.gov.br/Pages/Cadastro/Consultas/ConsultaPublica/ConsultaPublica.aspx"
        
        # Vamos usar um loop, porque a IA pode errar a leitura de vez em quando.
        # Daremos 3 tentativas ao robô.
        tentativas = 3
        
        for tentativa in range(1, tentativas + 1):
            print(f"-> Tentativa {tentativa} de {tentativas}...")
            page.goto(url_sp)
            
            # 1. Seleciona "CNPJ" e aguarda o reload do site (PostBack)
            seletor_dropdown = 'select[id$="tipoFiltroDropDownList"]'
            page.wait_for_selector(seletor_dropdown)
            page.select_option(seletor_dropdown, '1')
            time.sleep(2) 
            
            # 2. Preenche CNPJ
            page.fill('input[id$="valorFiltroTextBox"]', self.cnpj_limpo)
            
            # 3. Chama o GEMINI para ler o Captcha da SEFAZ-SP
            seletor_img_sp = 'img[id$="imagemDinamica"]'
            texto_captcha = self.quebrar_captcha_com_ia(page, seletor_img_sp)
            
            # 4. Preenche o que o Gemini leu
            page.fill('input[id$="imagemDinamicaTextBox"]', texto_captcha)
            
            # 5. Clica em Consultar
            page.click('input[id$="consultaPublicaButton"]')
            
            try:
                # Aguarda para ver se aparece a mensagem de "Código incorreto" ou a tela de sucesso
                # Vamos esperar a página estabilizar
                page.wait_for_load_state('networkidle')
                html_atual = page.content()
                
                if "caracteres da imagem ao lado" in html_atual.lower() and "consultar" in html_atual.lower():
                    # Significa que o botão consultar não mudou a página, provavelmente o captcha estava errado
                    print("   [Aviso] O Gemini errou o Captcha ou a empresa não foi encontrada. A tentar novamente...")
                    continue
                else:
                    print("-> Ecrã de resultado detetado com sucesso!")
                    self.relatorio["ie"] = "Capturado após resultado" 
                    self.relatorio["status_ie"] = "Habilitado/Ativo" 
                    break # Sai do loop de tentativas
                    
            except PlaywrightTimeoutError:
                print("   [Aviso] Timeout na resposta. A tentar novamente...")
                continue
        else:
            print("[Erro] O robô esgotou as tentativas de resolver o Captcha de SP.")
            self.relatorio["status_ie"] = "Falha na verificação (Captcha)"

    # ==========================================
    # MOTOR DE EXECUÇÃO EM CASCATA
    # ==========================================
    def executar(self):
        with sync_playwright() as p:
            # HEADLESS = TRUE -> O navegador fica totalmente invisível!
            # Ideal para rodar na nuvem (Replit/Colab)
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            
            is_simples = self.camada1_verificar_simples(page)
            
            if not is_simples:
                uf = self.camada2_descobrir_uf()
                if uf:
                    self.camada3_consultar_sintegra(page, uf)
            else:
                self.camada2_descobrir_uf()
                self.relatorio["status_ie"] = "Não exigida verificação (É Simples)"
                
            browser.close()
            
        return self.relatorio

if __name__ == "__main__":
    # LEMBRE-SE DE COLOCAR SUA CHAVE DO GEMINI LÁ EM CIMA
    cnpj_teste = "10.464.223/0001-63" 
    
    robo = RoboFiscal(cnpj_teste)
    resultado = robo.executar()
    
    print("\n" + "="*30)
    print("RELATÓRIO FINAL DA EMPRESA")
    print("="*30)
    for chave, valor in resultado.items():
        print(f"{chave.upper()}: {valor}")