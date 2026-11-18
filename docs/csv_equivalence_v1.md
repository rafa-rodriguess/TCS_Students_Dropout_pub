# Equivalência CSV SEMANTIC_CANONICAL_V1

O ZIP oficial da UCI preserva ausência como `?`. A fonte histórica usava campo vazio. O gate aceita um CSV de duas formas, sem regravar a fonte e sem alterar `config/protocol.yaml`:

1. `PASS_RAW`: o SHA-256 do arquivo inteiro é igual ao hash bruto congelado.
2. `SEMANTIC_CANONICAL_V1`: só para os arquivos elegíveis, o digest ordenado do registro inteiro, depois de trocar `?` por `""` apenas na coluna autorizada, coincide com a referência da auditoria, com a mesma ordem de linhas e a contagem exata de `?`.

`studentVle.csv` só passa por hash bruto. `courses.csv`, `vle.csv` e o ZIP continuam PENDING no protocolo. A normalização não entra no cálculo científico.
