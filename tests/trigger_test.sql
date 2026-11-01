BEGIN;
INSERT INTO ledger_account (owner_type, owner_id, account_type, currency) VALUES ('SYSTEM', NULL, 'BANK_CLEARING', 'NGN');
INSERT INTO journal_entry (reference, description, created_by, created_at) VALUES ('TEST-1', 'trigger test', 1, now());
INSERT INTO journal_line (entry_id, account_id, amount_kobo) VALUES (currval('journal_entry_id_seq'), currval('ledger_account_id_seq'), 500000);
SAVEPOINT s;
UPDATE journal_line SET amount_kobo = 300000;   -- should fail
ROLLBACK TO s;
DELETE FROM journal_line;                        -- should fail
ROLLBACK TO s;
TRUNCATE journal_line;                           -- should fail
ROLLBACK TO s;
INSERT INTO ledger_account (owner_type, owner_id, account_type, currency) VALUES ('SYSTEM', NULL, 'BANK_CLEARING', 'NGN');  -- duplicate, should fail
ROLLBACK;                                        -- leave the dev DB clean
