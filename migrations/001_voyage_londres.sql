PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS voyage_londres_inscriptions (
 id TEXT PRIMARY KEY, candidat_id TEXT NOT NULL UNIQUE, statut TEXT NOT NULL DEFAULT 'active' CHECK(statut IN ('active','annulee')),
 convention TEXT NOT NULL DEFAULT 'À faire', opco INTEGER NOT NULL DEFAULT 0, billet INTEGER NOT NULL DEFAULT 0,
 hebergement INTEGER NOT NULL DEFAULT 0, passeport INTEGER NOT NULL DEFAULT 0, numero_passeport TEXT,
 passeport_delivrance TEXT, passeport_expiration TEXT, immigration INTEGER NOT NULL DEFAULT 0,
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL, cancelled_at TEXT, FOREIGN KEY(candidat_id) REFERENCES candidats(id) ON DELETE RESTRICT
);
CREATE TABLE IF NOT EXISTS voyage_londres_documents (
 id TEXT PRIMARY KEY, inscription_id TEXT NOT NULL, categorie TEXT NOT NULL, nom_original TEXT NOT NULL,
 nom_stockage TEXT NOT NULL UNIQUE, mime_type TEXT NOT NULL, taille INTEGER NOT NULL, created_at TEXT NOT NULL,
 FOREIGN KEY(inscription_id) REFERENCES voyage_londres_inscriptions(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_voyage_statut ON voyage_londres_inscriptions(statut);
