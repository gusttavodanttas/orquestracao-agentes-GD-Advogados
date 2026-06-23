-- =============================================================================
-- schema.sql — GD Advogados · Captura de Publicações
-- Execute no SQL Editor do Supabase (pode ser rodado mais de uma vez com segurança)
-- =============================================================================

-- ---------------------------------------------------------------------------
-- 1. Escritórios (cada escritório é um tenant isolado)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS escritorios (
  id        UUID        DEFAULT gen_random_uuid() PRIMARY KEY,
  nome      TEXT        NOT NULL,
  criado_em TIMESTAMPTZ DEFAULT NOW()
);

-- ---------------------------------------------------------------------------
-- 2. Membros — mapeia usuários Supabase Auth a escritórios (para RLS futura)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS membros_escritorio (
  id            UUID    DEFAULT gen_random_uuid() PRIMARY KEY,
  user_id       UUID    NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  escritorio_id UUID    NOT NULL REFERENCES escritorios(id) ON DELETE CASCADE,
  papel         TEXT    NOT NULL DEFAULT 'membro',  -- 'dono' | 'membro'
  UNIQUE (user_id, escritorio_id)
);

-- ---------------------------------------------------------------------------
-- 3. OABs monitoradas por escritório
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS oabs_monitoradas (
  id            UUID    DEFAULT gen_random_uuid() PRIMARY KEY,
  escritorio_id UUID    NOT NULL REFERENCES escritorios(id) ON DELETE CASCADE,
  numero_oab    TEXT    NOT NULL,
  uf_oab        TEXT    NOT NULL,
  ativo         BOOLEAN NOT NULL DEFAULT TRUE,
  criado_em     TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE (escritorio_id, numero_oab, uf_oab)
);

-- ---------------------------------------------------------------------------
-- 4. Publicações capturadas do DJEN
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS publicacoes (
  id                    UUID    DEFAULT gen_random_uuid() PRIMARY KEY,
  escritorio_id         UUID    NOT NULL REFERENCES escritorios(id) ON DELETE CASCADE,
  numero_comunicacao    TEXT    NOT NULL,
  bruto                 JSONB   NOT NULL,             -- JSON bruto da API
  texto_limpo           TEXT,
  tipo_comunicacao      TEXT,
  tipo_documento        TEXT,
  data_disponibilizacao DATE,
  numero_processo       TEXT,
  tribunal              TEXT,
  capturado_em          TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE (escritorio_id, numero_comunicacao)          -- chave de upsert
);

-- ---------------------------------------------------------------------------
-- 5. Processos (derivados das publicações)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS processos (
  id              UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  escritorio_id   UUID NOT NULL REFERENCES escritorios(id) ON DELETE CASCADE,
  numero_processo TEXT NOT NULL,
  tribunal        TEXT,
  nome_classe     TEXT,
  criado_em       TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE (escritorio_id, numero_processo)
);

-- ---------------------------------------------------------------------------
-- 6. Prazos calculados conforme o CPC
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS prazos (
  id                    UUID    DEFAULT gen_random_uuid() PRIMARY KEY,
  escritorio_id         UUID    NOT NULL REFERENCES escritorios(id) ON DELETE CASCADE,
  publicacao_id         UUID    NOT NULL REFERENCES publicacoes(id) ON DELETE CASCADE,
  numero_processo       TEXT    NOT NULL,
  tipo_prazo            TEXT    NOT NULL,
  data_disponibilizacao DATE    NOT NULL,
  data_intimacao        DATE    NOT NULL,  -- Art. 231 I: 1º dia útil após publicação
  data_fim_prazo        DATE,              -- NULL se indeterminado (ex.: edital)
  dias_uteis            INTEGER,
  base_legal            TEXT,
  calculado_em          TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE (publicacao_id)                   -- um prazo por publicação
);

-- =============================================================================
-- Row Level Security — isola dados por escritório
-- =============================================================================

-- Habilitar RLS em todas as tabelas
ALTER TABLE escritorios          ENABLE ROW LEVEL SECURITY;
ALTER TABLE membros_escritorio   ENABLE ROW LEVEL SECURITY;
ALTER TABLE oabs_monitoradas     ENABLE ROW LEVEL SECURITY;
ALTER TABLE publicacoes          ENABLE ROW LEVEL SECURITY;
ALTER TABLE processos            ENABLE ROW LEVEL SECURITY;
ALTER TABLE prazos               ENABLE ROW LEVEL SECURITY;

-- Função auxiliar: retorna o escritorio_id do usuário autenticado
-- (usada pelas políticas abaixo — o script Python usa service_role, que ignora RLS)
CREATE OR REPLACE FUNCTION meu_escritorio_id()
RETURNS UUID LANGUAGE SQL STABLE SECURITY DEFINER AS $$
  SELECT escritorio_id
  FROM   membros_escritorio
  WHERE  user_id = auth.uid()
  LIMIT  1
$$;

-- Políticas para membros_escritorio
DROP POLICY IF EXISTS "membro_ve_propria_filiacao" ON membros_escritorio;
CREATE POLICY "membro_ve_propria_filiacao" ON membros_escritorio
  FOR SELECT USING (user_id = auth.uid());

-- Políticas para escritorios
DROP POLICY IF EXISTS "escritorio_acesso_proprio" ON escritorios;
CREATE POLICY "escritorio_acesso_proprio" ON escritorios
  FOR SELECT USING (id = meu_escritorio_id());

-- Políticas para oabs_monitoradas
DROP POLICY IF EXISTS "oab_acesso_por_escritorio" ON oabs_monitoradas;
CREATE POLICY "oab_acesso_por_escritorio" ON oabs_monitoradas
  FOR ALL USING (escritorio_id = meu_escritorio_id());

-- Políticas para publicacoes
DROP POLICY IF EXISTS "publicacao_leitura" ON publicacoes;
CREATE POLICY "publicacao_leitura" ON publicacoes
  FOR SELECT USING (escritorio_id = meu_escritorio_id());

DROP POLICY IF EXISTS "publicacao_escrita" ON publicacoes;
CREATE POLICY "publicacao_escrita" ON publicacoes
  FOR INSERT WITH CHECK (escritorio_id = meu_escritorio_id());

DROP POLICY IF EXISTS "publicacao_atualizacao" ON publicacoes;
CREATE POLICY "publicacao_atualizacao" ON publicacoes
  FOR UPDATE USING (escritorio_id = meu_escritorio_id());

-- Políticas para processos
DROP POLICY IF EXISTS "processo_acesso_por_escritorio" ON processos;
CREATE POLICY "processo_acesso_por_escritorio" ON processos
  FOR ALL USING (escritorio_id = meu_escritorio_id());

-- Políticas para prazos
DROP POLICY IF EXISTS "prazo_acesso_por_escritorio" ON prazos;
CREATE POLICY "prazo_acesso_por_escritorio" ON prazos
  FOR ALL USING (escritorio_id = meu_escritorio_id());

-- =============================================================================
-- Seed — cria o escritório GD Advogados (seguro rodar mais de uma vez)
-- =============================================================================
INSERT INTO escritorios (nome)
SELECT 'GD Advogados'
WHERE NOT EXISTS (
  SELECT 1 FROM escritorios WHERE nome = 'GD Advogados'
);

-- Exibe o UUID que você deve copiar para o .env como ESCRITORIO_ID
SELECT id AS "ESCRITORIO_ID — copie este valor para o .env", nome
FROM   escritorios
WHERE  nome = 'GD Advogados';
