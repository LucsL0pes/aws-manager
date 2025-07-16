import sys
import os
import subprocess
import json
import hashlib
from configparser import ConfigParser
from pathlib import Path
import boto3

# ==============================================================================
#           Script de busca por recursos em AWS Accounts via SSO (Versão Python)
#
# Como utilizá-lo:
#   - Necessário ter Python 3, Boto3 e AWS CLI v2 instalados.
#   - Execute com: python aws_search.py
# ==============================================================================

# --- Configuração ---
SSO_PROFILE = "IAM"
ROUTE53_SEARCH_ACCOUNT_ID = "979633380910"
# --------------------

# Classe para gerenciar as cores do terminal
class Colors:
    BLUE = "\033[1;34m"
    GREEN = "\033[1;32m"
    RED = "\033[1;31m"
    YELLOW = "\033[1;33m"
    GRAY = "\033[0;90m"
    NC = "\033[0m"  # Sem Cor

# --- Funções Auxiliares ---

def print_color(color, text):
    """Imprime texto com a cor especificada."""
    print(f"{color}{text}{Colors.NC}")

def get_sso_config_value(profile_name, key):
    """
    Lê um valor específico (como sso_start_url ou sso_region) do perfil no
    arquivo de configuração da AWS.
    """
    try:
        config_path = Path.home() / ".aws" / "config"
        parser = ConfigParser()
        parser.read(config_path)

        profile_section = f"profile {profile_name}" if profile_name else "default"
        if not parser.has_section(profile_section):
            print_color(Colors.RED, f"ERRO: Perfil '{profile_name}' não encontrado em {config_path}")
            return None

        return parser.get(profile_section, key, fallback=None)

    except Exception as e:
        print_color(Colors.RED, f"ERRO ao ler o arquivo de configuração da AWS: {e}")
        return None

def get_sso_token(profile_name, sso_start_url):
    """
    Busca o token de acesso do cache do SSO.
    """
    try:
        sha1 = hashlib.sha1(sso_start_url.encode()).hexdigest()
        cache_path = Path.home() / ".aws" / "sso" / "cache" / f"{sha1}.json"

        if not cache_path.exists():
            print_color(Colors.RED, "ERRO: Arquivo de cache do SSO não encontrado. Tente fazer login novamente.")
            return None
            
        with open(cache_path) as f:
            data = json.load(f)
        return data.get("accessToken")

    except Exception as e:
        print_color(Colors.RED, f"ERRO ao ler o token do SSO: {e}")
        return None

def display_menu(title, options):
    """Exibe um menu customizado e retorna a escolha do usuário."""
    print_color(Colors.YELLOW, f"\n{title}")
    for i, option in enumerate(options):
        print(f"  {i+1}) {option}")
    
    print("")
    choice = input("Sua opção: ")
    
    if choice.isdigit() and 1 <= int(choice) <= len(options):
        return int(choice)
    else:
        return None

def display_cdn_details(distribution, account_name, account_id):
    """Exibe os detalhes formatados de uma CDN encontrada."""
    dist_id = distribution.get("Id", "N/A")
    dist_domain = distribution.get("DomainName", "N/A")
    dist_comment = distribution.get("Comment", "")
    aliases = distribution.get("Aliases", {}).get("Items", [])
    origins = distribution.get("Origins", {}).get("Items", [])

    print(f"\r{' ' * 80}\r", end="")
    print(f"[{Colors.GREEN}ENCONTRADO{Colors.NC}] Na conta {Colors.YELLOW}{account_name}{Colors.NC} ({account_id})")
    
    print(f"\n  {Colors.BLUE}{'ID da Distribuição':<20}:{Colors.NC} {dist_id}")
    print(f"  {Colors.BLUE}{'DomainName':<20}:{Colors.NC} {dist_domain}")
    print(f"  {Colors.BLUE}{'Descrição':<20}:{Colors.NC} {dist_comment}")
    
    print(f"  {Colors.BLUE}{'Aliases':<20}:{Colors.NC}")
    if aliases:
        for alias in aliases:
            print(f"    - {alias}")
    else:
        print("    - (nenhum)")
        
    print(f"  {Colors.BLUE}{'Origens':<20}:{Colors.NC}")
    if origins:
        for origin in origins:
            print(f"    - {origin.get('Id', 'N/A')}")
    else:
        print("    - (nenhuma)")

def display_r53_record_details(record, zone_name):
    """Exibe os detalhes formatados de um registro DNS encontrado."""
    record_name, record_type = record.get("Name", "N/A"), record.get("Type", "N/A")
    record_values = [rr.get("Value", "N/A") for rr in record.get("ResourceRecords", [])]

    print_color(Colors.GREEN, f"Registro encontrado na Zona {Colors.YELLOW}{zone_name}{Colors.NC}")
    print(f"  {Colors.BLUE}{'Nome do Registro':<20}:{Colors.NC} {record_name}")
    print(f"  {Colors.BLUE}{'Tipo':<20}:{Colors.NC} {record_type}")
    print(f"  {Colors.BLUE}{'Valores':<20}:{Colors.NC}")
    if record_values:
        for value in record_values:
            print(f"    - {value}")
    else:
        print("    - (nenhum)")

################################################################################
# FUNÇÃO PRINCIPAL DE BUSCA DO CLOUDFRONT
################################################################################
def run_cloudfront_search(access_token, sso_region, search_behavior):
    """Executa o fluxo completo de busca por CDNs."""
    cdn_options = ["Por ID da Distribuição", "Por DomainName do CloudFront", "Por Aliases (CNAMEs)"]
    choice = display_menu("Como você deseja buscar a CDN?", cdn_options)
    
    if choice is None:
        print_color(Colors.RED, "Opção inválida."); return

    search_map = {1: "Id", 2: "DomainName", 3: "Aliases"}
    search_type = search_map[choice]

    print("")
    search_value = input(f"Digite o valor para buscar por '{search_type}': ")
    if not search_value:
        print_color(Colors.RED, "O valor de busca não pode ser vazio."); return

    print_color(Colors.BLUE, "\n" + "="*80)
    print_color(Colors.BLUE, "Iniciando busca em todas as contas...")
    print_color(Colors.BLUE, "="*80)

    overall_found_count = 0
    try:
        # Cria um cliente SSO para listar contas e obter credenciais
        sso_client = boto3.client('sso', region_name=sso_region)
        paginator = sso_client.get_paginator('list_accounts')
        
        all_accounts = []
        for page in paginator.paginate(accessToken=access_token):
            all_accounts.extend(page['accountList'])
        
        sorted_accounts = sorted(all_accounts, key=lambda x: x['accountName'])

        for account in sorted_accounts:
            account_id, account_name = account['accountId'], account['accountName']
            print(f"[{Colors.YELLOW}CONTA{Colors.NC}] Buscando em {Colors.YELLOW}{account_name}{Colors.NC} ({account_id})...", end="\r")
            sys.stdout.flush()

            found_in_account = False
            roles = sso_client.list_account_roles(accessToken=access_token, accountId=account_id).get('roleList', [])
            
            for role in roles:
                role_name = role['roleName']
                try:
                    creds_response = sso_client.get_role_credentials(roleName=role_name, accountId=account_id, accessToken=access_token)
                    creds = creds_response.get('roleCredentials', {})
                    if not creds: continue

                    cloudfront_client = boto3.client('cloudfront', aws_access_key_id=creds['accessKeyId'], aws_secret_access_key=creds['secretAccessKey'], aws_session_token=creds['sessionToken'])
                    paginator_dist = cloudfront_client.get_paginator('list_distributions')

                    for page_dist in paginator_dist.paginate():
                        distributions = page_dist.get('DistributionList', {})
                        if 'Items' not in distributions: continue
                        
                        for dist in distributions.get('Items', []):
                            match = False
                            if search_type == "Id" and dist.get('Id') == search_value: match = True
                            elif search_type == "DomainName" and dist.get('DomainName') == search_value: match = True
                            elif search_type == "Aliases" and search_value in dist.get('Aliases', {}).get('Items', []): match = True

                            if match:
                                display_cdn_details(dist, account_name, account_id)
                                found_in_account = True
                                overall_found_count += 1
                                if search_behavior == 'find_first': return 
                                else: break
                except Exception:
                    continue
            
            if found_in_account and search_behavior == 'find_all': continue
            if not found_in_account:
                print(f"[{Colors.GRAY}NÃO ENCONTRADO{Colors.NC}] Na conta {Colors.YELLOW}{account_name}{Colors.NC} ({account_id}){' ' * 20}")
    finally:
        if overall_found_count == 0:
            print_color(Colors.YELLOW, "\nBusca finalizada. Nenhum recurso encontrado com os critérios informados.")
        else:
            print_color(Colors.GREEN, "\nBusca finalizada.")

################################################################################
# FUNÇÃO PRINCIPAL DE BUSCA DO ROUTE 53
################################################################################
def run_route53_search(access_token, sso_region):
    """
    Executa o fluxo de busca por registros DNS, consolidando os resultados
    para exibição no final.
    """
    r53_options = ["Pelo Nome do Registro", "Pelo Valor do Registro"]
    choice = display_menu("Como você deseja buscar o registro DNS?", r53_options)
    if choice is None:
        print_color(Colors.RED, "Opção inválida."); return

    search_type = "Name" if choice == 1 else "Value"
    print("")
    search_value = input(f"Digite o valor para buscar por '{search_type}': ")
    if not search_value:
        print_color(Colors.RED, "O valor de busca não pode ser vazio."); return
    
    print_color(Colors.BLUE, "\n" + "="*80)
    print_color(Colors.BLUE, f"Iniciando busca na conta {ROUTE53_SEARCH_ACCOUNT_ID}...")
    print_color(Colors.BLUE, "="*80)

    # Lista para armazenar os resultados encontrados durante a busca
    found_records = []
    
    try:
        sso_client = boto3.client('sso', region_name=sso_region)
        
        target_account_list = sso_client.list_accounts(accessToken=access_token).get('accountList', [])
        target_account = next((acc for acc in target_account_list if acc['accountId'] == ROUTE53_SEARCH_ACCOUNT_ID), None)
        if not target_account:
            print_color(Colors.RED, f"ERRO: Conta {ROUTE53_SEARCH_ACCOUNT_ID} não encontrada ou inacessível."); return
        account_name = target_account['accountName']

        roles = sso_client.list_account_roles(accessToken=access_token, accountId=ROUTE53_SEARCH_ACCOUNT_ID).get('roleList', [])
        if not roles:
            print_color(Colors.RED, f"Nenhuma role encontrada para a conta {ROUTE53_SEARCH_ACCOUNT_ID}.")
            return

        role_name = roles[0]['roleName']
        creds_response = sso_client.get_role_credentials(roleName=role_name, accountId=ROUTE53_SEARCH_ACCOUNT_ID, accessToken=access_token)
        creds = creds_response.get('roleCredentials', {})
        if not creds:
            print_color(Colors.RED, f"Falha ao obter credenciais para a conta {ROUTE53_SEARCH_ACCOUNT_ID}.")
            return

        route53_client = boto3.client('route53', aws_access_key_id=creds['accessKeyId'], aws_secret_access_key=creds['secretAccessKey'], aws_session_token=creds['sessionToken'])
        
        hosted_zones = route53_client.list_hosted_zones().get('HostedZones', [])
        for zone in hosted_zones:
            zone_id, zone_name = zone['Id'], zone['Name']
            
            # **MUDANÇA 1**: Exibe "ANALISANDO" e mantém o cursor na mesma linha.
            print(f"[{Colors.YELLOW}ANALISANDO{Colors.NC}] Zona: {zone_name}...", end="\r", flush=True)

            paginator = route53_client.get_paginator('list_resource_record_sets')
            for page in paginator.paginate(HostedZoneId=zone_id):
                for record in page.get('ResourceRecordSets', []):
                    match = False
                    if search_type == "Name" and search_value.lower() in record.get('Name', '').lower():
                        match = True
                    elif search_type == "Value":
                        for rr in record.get('ResourceRecords', []):
                            if search_value.lower() in rr.get('Value', '').lower():
                                match = True
                                break
                    
                    if match:
                        found_records.append({
                            "record": record,
                            "zone_name": zone_name,
                            "account_name": account_name
                        })
            
            # **MUDANÇA 2**: Sobrescreve a linha "ANALISANDO" com "ANALISADO" e pula para a próxima linha.
            # Adicionamos espaços no final para garantir que a linha anterior seja completamente apagada.
            print(f"[{Colors.GRAY}ANALISADO{Colors.NC}]  Zona: {zone_name}{' ' * 40}")


    except Exception as e:
        print_color(Colors.RED, f"Ocorreu um erro durante a busca: {e}")

    # --- Bloco de Exibição dos Resultados Consolidados ---
    if not found_records:
        print_color(Colors.YELLOW, "\nBusca finalizada. Nenhum registro encontrado com os critérios informados.")
    else:
        print_color(Colors.GREEN, f"\nBusca finalizada. Encontrado(s) {len(found_records)} resultado(s):")
        for item in found_records:
            print("") # Linha em branco para separar os registros
            display_r53_record_details(
                record=item['record'],
                zone_name=item['zone_name'],
            )

# ==============================================================================
# INÍCIO DA EXECUÇÃO DO SCRIPT
# ==============================================================================
if __name__ == "__main__":
    profile_arg = ['--profile', SSO_PROFILE] if SSO_PROFILE else []

    # --- Login ---
    print_color(Colors.BLUE, "Iniciando login no AWS IAM Identity Center...")
    try:
        subprocess.run(['aws'] + profile_arg + ['sso', 'login'], check=True)
        print_color(Colors.GREEN, "\nLogin realizado com sucesso.")
    except (subprocess.CalledProcessError, FileNotFoundError):
        print_color(Colors.RED, "Falha no login do SSO. Verifique se a AWS CLI está instalada e o perfil configurado.")
        sys.exit(1)

    # --- Obtenção de Tokens e Configuração ---
    # **CORREÇÃO**: Lê explicitamente sso_start_url e sso_region do arquivo de config.
    sso_start_url = get_sso_config_value(SSO_PROFILE, 'sso_start_url')
    sso_region = get_sso_config_value(SSO_PROFILE, 'sso_region')
    access_token = get_sso_token(SSO_PROFILE, sso_start_url)
    
    if not all([sso_start_url, sso_region, access_token]):
        print_color(Colors.RED, "Não foi possível obter a configuração de SSO (região ou token). Saindo.")
        sys.exit(1)

    # --- Menu Principal ---
    while True:
        main_options = ["Buscar por CDNs do CloudFront","Buscar por Registros DNS no Route 53", "Sair"]
        choice = display_menu("Selecione o tipo de recurso que deseja buscar:", main_options)

        if choice == 1:
            run_cloudfront_search(access_token, sso_region, search_behavior="find_first")
        elif choice == 2:
            # CHAMA A NOVA FUNÇÃO, PASSANDO O COMPORTAMENTO "find_all"
            run_route53_search(access_token, sso_region)
        elif choice == 3:
            print_color(Colors.RED, "Saindo.")
            break
        else:
            print_color(Colors.RED, "Opção inválida, por favor tente novamente.")