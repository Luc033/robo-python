# Este arquivo transforma o seu robô em uma API na nuvem.
# Requisitos: pip install flask playwright requests google-generativeai flask-cors
import os
from flask import Flask, request, jsonify
from flask_cors import CORS
from robo_fiscal import RoboFiscal # Importa a classe do robô que já criamos

app = Flask(__name__)
# O CORS permite que o seu Deskhub (HTML) faça requisições para este servidor Python
CORS(app) 

@app.route('/consultar_cnpj', methods=['GET'])
def consultar_cnpj():
    cnpj_recebido = request.args.get('cnpj')
    
    if not cnpj_recebido:
        return jsonify({"erro": "CNPJ não informado"}), 400
        
    print(f"Nova requisição recebida no servidor para o CNPJ: {cnpj_recebido}")
    
    try:
        # Instancia e roda o robô
        robo = RoboFiscal(cnpj_recebido)
        resultado = robo.executar()
        
        # Devolve o dicionário como JSON para o seu Deskhub
        return jsonify(resultado), 200
        
    except Exception as e:
        print(f"Erro no servidor: {e}")
        return jsonify({"erro": "Falha interna ao consultar o CNPJ", "detalhe": str(e)}), 500

if __name__ == '__main__':
    # Roda o servidor na porta 5000
    app.run(host='0.0.0.0', port=5000)