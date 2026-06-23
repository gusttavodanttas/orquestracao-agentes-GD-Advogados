# Captura de Publicações — Regras do Projeto

## 1. Comunicação
Este projeto é mantido por um advogado, não por um programador.
- Explique todas as decisões técnicas em **português simples**, sem jargão desnecessário.
- Quando houver mais de uma forma de resolver um problema, apresente as opções com prós e contras antes de implementar.

## 2. Fonte de dados
- A **única** fonte oficial de publicações é a API pública do DJEN:
  `https://comunicaapi.pje.jus.br/api/v1/comunicacao`
- **Nunca** fazer raspagem (scraping) de sites de tribunais.
- Qualquer integração com nova fonte deve ser discutida e aprovada antes de ser codificada.

## 3. Cálculo de prazos
- O cálculo de prazos processuais deve ser uma **função determinística**, implementada seguindo as regras do CPC (arts. 219–224).
- **Nunca** usar IA, LLM ou lógica probabilística para decidir, inferir ou sugerir datas de prazo.
- Feriados e suspensões devem vir de uma lista mantida manualmente ou de fonte oficial auditável.

## 4. Privacidade e LGPD
- Dados de partes (nomes, CPF, CNPJ, endereços, conteúdo de intimações) são **dados sensíveis** sob a LGPD.
- **Nunca** registrar esses dados em logs em texto aberto (console, arquivos de log, etc.).
- Ao exibir ou armazenar, aplicar mascaramento ou criptografia conforme necessário.
- Em caso de dúvida sobre o tratamento de um dado, perguntar antes de implementar.

## 5. Controle de versão — segurança antes de mudanças
- Antes de qualquer alteração relevante (nova funcionalidade, refatoração, mudança de esquema), **fazer commit** do estado atual para que seja possível reverter.
- Nunca acumular mudanças grandes sem commits intermediários.

## 6. Revisão antes de aplicar
- **Sempre** mostrar o diff completo e explicar o que vai mudar — e por quê — antes de aplicar qualquer modificação.
- Aguardar confirmação explícita do usuário antes de gravar arquivos em mudanças significativas.
