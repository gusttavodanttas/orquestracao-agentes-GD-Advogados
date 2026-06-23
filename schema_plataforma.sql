-- ===========================================================================
-- schema_plataforma.sql — GD Advogados · Plataforma Unificada
-- Extensão do schema existente — seguro rodar múltiplas vezes
-- Execute no SQL Editor do Supabase após o schema.sql original
-- ===========================================================================

-- ---------------------------------------------------------------------------
-- Agentes registrados
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS agentes (
  id            UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  escritorio_id UUID NOT NULL REFERENCES escritorios(id) ON DELETE CASCADE,
  nome          TEXT NOT NULL,
  descricao     TEXT,
  webhook_key   TEXT NOT NULL DEFAULT encode(gen_random_bytes(32), 'hex'),
  icone         TEXT DEFAULT '🤖',
  cor           TEXT DEFAULT '#185fa5',
  ativo         BOOLEAN NOT NULL DEFAULT TRUE,
  criado_em     TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE (escritorio_id, nome)
);

-- ---------------------------------------------------------------------------
-- Fila de tarefas — Central de Despacho
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS tarefas (
  id              UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  escritorio_id   UUID NOT NULL REFERENCES escritorios(id) ON DELETE CASCADE,
  agente_id       UUID REFERENCES agentes(id),
  docket          TEXT NOT NULL,
  tipo            TEXT NOT NULL DEFAULT 'outro',
  titulo          TEXT NOT NULL,
  conteudo        JSONB,
  prioridade      TEXT NOT NULL DEFAULT 'media' CHECK (prioridade IN ('alta','media','baixa')),
  status          TEXT NOT NULL DEFAULT 'pendente' CHECK (status IN ('pendente','em_analise','aprovado','rejeitado','editado')),
  numero_processo TEXT,
  publicacao_id   UUID REFERENCES publicacoes(id),
  decidido_em     TIMESTAMPTZ,
  decidido_por    UUID REFERENCES auth.users(id),
  observacao      TEXT,
  whatsapp_enviado BOOLEAN DEFAULT FALSE,
  criado_em       TIMESTAMPTZ DEFAULT NOW()
);

-- Contador de docket por escritório
CREATE TABLE IF NOT EXISTS docket_counter (
  escritorio_id UUID PRIMARY KEY REFERENCES escritorios(id),
  ultimo        INTEGER NOT NULL DEFAULT 0
);

-- ---------------------------------------------------------------------------
-- Log do orquestrador
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS log_orquestrador (
  id             UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  escritorio_id  UUID NOT NULL REFERENCES escritorios(id) ON DELETE CASCADE,
  tarefa_id      UUID REFERENCES tarefas(id),
  evento         TEXT NOT NULL,
  agente_origem  TEXT,
  agente_destino TEXT,
  raciocinio     TEXT,
  acao_tomada    TEXT,
  whatsapp_enviado BOOLEAN DEFAULT FALSE,
  criado_em      TIMESTAMPTZ DEFAULT NOW()
);

-- ---------------------------------------------------------------------------
-- CRM — Leads
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS leads (
  id              UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  escritorio_id   UUID NOT NULL REFERENCES escritorios(id) ON DELETE CASCADE,
  nome            TEXT NOT NULL,
  email           TEXT,
  telefone        TEXT,
  area            TEXT,
  origem          TEXT DEFAULT 'manual',
  status_pipeline TEXT NOT NULL DEFAULT 'novo'
    CHECK (status_pipeline IN ('novo','contato','qualificado','proposta','fechado','perdido')),
  score           INTEGER,
  observacoes     TEXT,
  criado_em       TIMESTAMPTZ DEFAULT NOW(),
  atualizado_em   TIMESTAMPTZ DEFAULT NOW()
);

-- ---------------------------------------------------------------------------
-- CRM — Clientes
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS clientes (
  id             UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  escritorio_id  UUID NOT NULL REFERENCES escritorios(id) ON DELETE CASCADE,
  lead_id        UUID REFERENCES leads(id),
  tipo           TEXT NOT NULL DEFAULT 'pf' CHECK (tipo IN ('pf','pj')),
  nome           TEXT NOT NULL,
  cpf_cnpj       TEXT,
  email          TEXT,
  telefone       TEXT,
  area_principal TEXT,
  ativo          BOOLEAN NOT NULL DEFAULT TRUE,
  criado_em      TIMESTAMPTZ DEFAULT NOW()
);

-- ---------------------------------------------------------------------------
-- CRM — Processos (extensão da tabela existente)
-- ---------------------------------------------------------------------------
ALTER TABLE processos ADD COLUMN IF NOT EXISTS cliente_id  UUID REFERENCES clientes(id);
ALTER TABLE processos ADD COLUMN IF NOT EXISTS area        TEXT;
ALTER TABLE processos ADD COLUMN IF NOT EXISTS status      TEXT DEFAULT 'ativo';
ALTER TABLE processos ADD COLUMN IF NOT EXISTS valor_causa NUMERIC(12,2);
ALTER TABLE processos ADD COLUMN IF NOT EXISTS fase        TEXT;

-- ---------------------------------------------------------------------------
-- Índices
-- ---------------------------------------------------------------------------
CREATE INDEX IF NOT EXISTS idx_tarefas_status      ON tarefas(escritorio_id, status, criado_em DESC);
CREATE INDEX IF NOT EXISTS idx_tarefas_prioridade  ON tarefas(escritorio_id, prioridade);
CREATE INDEX IF NOT EXISTS idx_leads_pipeline      ON leads(escritorio_id, status_pipeline);
CREATE INDEX IF NOT EXISTS idx_log_orq             ON log_orquestrador(escritorio_id, criado_em DESC);

-- ---------------------------------------------------------------------------
-- RLS
-- ---------------------------------------------------------------------------
ALTER TABLE agentes          ENABLE ROW LEVEL SECURITY;
ALTER TABLE tarefas          ENABLE ROW LEVEL SECURITY;
ALTER TABLE log_orquestrador ENABLE ROW LEVEL SECURITY;
ALTER TABLE leads            ENABLE ROW LEVEL SECURITY;
ALTER TABLE clientes         ENABLE ROW LEVEL SECURITY;
ALTER TABLE docket_counter   ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "agentes_rls"   ON agentes;
DROP POLICY IF EXISTS "tarefas_rls"   ON tarefas;
DROP POLICY IF EXISTS "log_rls"       ON log_orquestrador;
DROP POLICY IF EXISTS "leads_rls"     ON leads;
DROP POLICY IF EXISTS "clientes_rls"  ON clientes;
DROP POLICY IF EXISTS "docket_rls"    ON docket_counter;

CREATE POLICY "agentes_rls"  ON agentes          FOR ALL USING (escritorio_id = meu_escritorio_id());
CREATE POLICY "tarefas_rls"  ON tarefas          FOR ALL USING (escritorio_id = meu_escritorio_id());
CREATE POLICY "log_rls"      ON log_orquestrador FOR ALL USING (escritorio_id = meu_escritorio_id());
CREATE POLICY "leads_rls"    ON leads            FOR ALL USING (escritorio_id = meu_escritorio_id());
CREATE POLICY "clientes_rls" ON clientes         FOR ALL USING (escritorio_id = meu_escritorio_id());
CREATE POLICY "docket_rls"   ON docket_counter   FOR ALL USING (escritorio_id = meu_escritorio_id());

-- ---------------------------------------------------------------------------
-- Função: próximo docket
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION proximo_docket(p_escritorio_id UUID)
RETURNS TEXT LANGUAGE plpgsql SECURITY DEFINER AS $$
DECLARE
  v_num INTEGER;
  v_ano TEXT := to_char(NOW(), 'YYYY');
BEGIN
  INSERT INTO docket_counter (escritorio_id, ultimo) VALUES (p_escritorio_id, 1)
  ON CONFLICT (escritorio_id) DO UPDATE SET ultimo = docket_counter.ultimo + 1
  RETURNING ultimo INTO v_num;
  RETURN 'GD-' || v_ano || '-' || lpad(v_num::TEXT, 4, '0');
END;
$$;

-- ---------------------------------------------------------------------------
-- Seed — agentes iniciais
-- ---------------------------------------------------------------------------
INSERT INTO agentes (escritorio_id, nome, descricao, icone, cor)
SELECT id, 'Monitor DJEN',         'Captura publicações do DJe e calcula prazos CPC', '⚖️', '#185fa5' FROM escritorios WHERE nome = 'GD Advogados'
ON CONFLICT (escritorio_id, nome) DO NOTHING;

INSERT INTO agentes (escritorio_id, nome, descricao, icone, cor)
SELECT id, 'Agente Comercial',     'Qualifica leads e prepara propostas',               '💼', '#854f0b' FROM escritorios WHERE nome = 'GD Advogados'
ON CONFLICT (escritorio_id, nome) DO NOTHING;

INSERT INTO agentes (escritorio_id, nome, descricao, icone, cor)
SELECT id, 'Assistente de Petições','Redige minutas de manifestações e petições',       '📝', '#3b6d11' FROM escritorios WHERE nome = 'GD Advogados'
ON CONFLICT (escritorio_id, nome) DO NOTHING;

INSERT INTO agentes (escritorio_id, nome, descricao, icone, cor)
SELECT id, 'Orquestrador',         'Recebe eventos e roteia para os agentes corretos',  '🧠', '#533ab7' FROM escritorios WHERE nome = 'GD Advogados'
ON CONFLICT (escritorio_id, nome) DO NOTHING;

-- Inicializa contador de docket
INSERT INTO docket_counter (escritorio_id, ultimo)
SELECT id, 0 FROM escritorios WHERE nome = 'GD Advogados'
ON CONFLICT DO NOTHING;

-- Exibe chaves de webhook (salve antes de fechar)
SELECT nome, icone, webhook_key FROM agentes
WHERE escritorio_id = (SELECT id FROM escritorios WHERE nome = 'GD Advogados')
ORDER BY criado_em;
