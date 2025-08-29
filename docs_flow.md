# Fluxo de Conversa (State Machine)

| Estado         | Pergunta/ação                                                                                                                                  | Próximo estado             |
|----------------|-------------------------------------------------------------------------------------------------------------------------------------------------|----------------------------|
| ASK_MODE/START | Saudação e escolha: 1) Anônima 2) Identificada                                                                                                  | ASK_CATEGORY ou ASK_CONSENT |
| ASK_CONSENT    | Consentimento LGPD para denúncias identificadas                                                                                                  | ASK_NAME ou ASK_CATEGORY    |
| ASK_NAME       | Captura do nome (ou PULAR)                                                                                                                       | ASK_EMAIL                   |
| ASK_EMAIL      | Captura do e-mail (ou PULAR)                                                                                                                     | ASK_CATEGORY                |
| ASK_CATEGORY   | Categoria (1..5)                                                                                                                                 | ASK_DESCRIPTION             |
| ASK_DESCRIPTION| Descrição livre (mín. 10 caracteres)                                                                                                            | ASK_MEDIA                   |
| ASK_MEDIA      | Anexos (ou PULAR). Se mídia recebida, registra `MediaUrl*` e `ContentType`                                                                       | ASK_WHEN                    |
| ASK_WHEN       | Quando ocorreu (tentativa de parsing natural)                                                                                                    | ASK_WHERE                   |
| ASK_WHERE      | Onde ocorreu                                                                                                                                    | ASK_WHO                     |
| ASK_WHO        | Envolvidos (opcional)                                                                                                                           | ASK_RETURN                  |
| ASK_RETURN     | 1) Protocolo  2) E-mail                                                                                                                          | CONFIRM / ASK_EMAIL         |
| CONFIRM        | CONFIRMAR ou CANCELAR                                                                                                                            | DONE                        |

Comandos globais: `menu`, `cancelar`, `status <protocolo>`.
