-- Fixture źródła migracji RAGFlow → Wawelsky Dragon (WP E4-6a, zadanie T1).
-- Zawartość: schemat bazy `rag_flow` RAGFlow v0.24.0 + DDL tabel `ai_hub_*` (hub-compat).
-- Plik jest wyłącznie zrzutem/wzorem — nie zawiera danych (te są w `data.sql`).
--
-- Pochodzenie:
--   obraz RAGFlow:  infiniflow/ragflow:v0.24.0
--                   (infiniflow/ragflow@sha256:508cc283f5d61d1e565820a8e0ae8d98f9a8ac4b3b8cf7aefc5f0093e4bb4c50)
--   obraz MySQL:    mysql:8.0.39 (mysql@sha256:ccb8f749bb5e59f9f8f03bf7282c7ef27a93a1814a24f0a8a926fb4e19b7fb97)
--   serwer:         MySQL 8.0.39, mysqldump 8.0.39
--   data zrzutu:    2026-09-30T14:38:01Z (UTC)
--   stos:           tools/contract-recorder/compose.v0.24.0.yml
--                   postawiony przez:
--                     uv run --script tools/contract-recorder/record.py \
--                       --version v0.24.0 --bootstrap-only --keep
--                   (projekt compose `wd-rec-v0-24-0`, port 18380)
--   komenda zrzutu:
--                     docker exec wd-rec-v0-24-0-mysql-1 mysqldump -uroot -p*** \
--                       --no-data --skip-comments --skip-add-drop-table rag_flow
--   DDL `ai_hub_*`: przepisane (a nie zrzucone) z plików projektu hub-compat, tylko odczyt:
--                     ../hub-compat/raglow-service/ragflow-user-api/src/services/migrations.ts
--                     ../hub-compat/raglow-service/sharepoint-sync/src/services/migrations.ts
--                   Konwersja TypeScript → MySQL: BOOLEAN → tinyint(1), INDEX → KEY,
--                   JSON → json, PRIMARY KEY/UNIQUE KEY inline → klauzule tabeli,
--                   CHARACTER SET/COLLATE → ENGINE=InnoDB DEFAULT CHARSET/COLLATE.
--
-- Tabele RAGFlow poniżej są zrzutem 1:1 (bez zmian ręcznych). Tabele `ai_hub_*`
-- znajdują się na końcu pliku.

/*!40101 SET @OLD_CHARACTER_SET_CLIENT=@@CHARACTER_SET_CLIENT */;
/*!40101 SET @OLD_CHARACTER_SET_RESULTS=@@CHARACTER_SET_RESULTS */;
/*!40101 SET @OLD_COLLATION_CONNECTION=@@COLLATION_CONNECTION */;
/*!50503 SET NAMES utf8mb4 */;
/*!40103 SET @OLD_TIME_ZONE=@@TIME_ZONE */;
/*!40103 SET TIME_ZONE='+00:00' */;
/*!40014 SET @OLD_UNIQUE_CHECKS=@@UNIQUE_CHECKS, UNIQUE_CHECKS=0 */;
/*!40014 SET @OLD_FOREIGN_KEY_CHECKS=@@FOREIGN_KEY_CHECKS, FOREIGN_KEY_CHECKS=0 */;
/*!40101 SET @OLD_SQL_MODE=@@SQL_MODE, SQL_MODE='NO_AUTO_VALUE_ON_ZERO' */;
/*!40111 SET @OLD_SQL_NOTES=@@SQL_NOTES, SQL_NOTES=0 */;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `api_4_conversation` (
  `id` varchar(32) COLLATE utf8mb4_unicode_ci NOT NULL,
  `create_time` bigint DEFAULT NULL,
  `create_date` datetime DEFAULT NULL,
  `update_time` bigint DEFAULT NULL,
  `update_date` datetime DEFAULT NULL,
  `name` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `dialog_id` varchar(32) COLLATE utf8mb4_unicode_ci NOT NULL,
  `user_id` varchar(255) COLLATE utf8mb4_unicode_ci NOT NULL,
  `exp_user_id` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `message` longtext COLLATE utf8mb4_unicode_ci,
  `reference` longtext COLLATE utf8mb4_unicode_ci,
  `tokens` int NOT NULL,
  `source` varchar(16) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `dsl` longtext COLLATE utf8mb4_unicode_ci,
  `duration` float NOT NULL,
  `round` int NOT NULL,
  `thumb_up` int NOT NULL,
  `errors` text COLLATE utf8mb4_unicode_ci,
  PRIMARY KEY (`id`),
  KEY `api4conversation_create_time` (`create_time`),
  KEY `api4conversation_create_date` (`create_date`),
  KEY `api4conversation_update_time` (`update_time`),
  KEY `api4conversation_update_date` (`update_date`),
  KEY `api4conversation_dialog_id` (`dialog_id`),
  KEY `api4conversation_user_id` (`user_id`),
  KEY `api4conversation_exp_user_id` (`exp_user_id`),
  KEY `api4conversation_source` (`source`),
  KEY `api4conversation_duration` (`duration`),
  KEY `api4conversation_round` (`round`),
  KEY `api4conversation_thumb_up` (`thumb_up`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `api_token` (
  `create_time` bigint DEFAULT NULL,
  `create_date` datetime DEFAULT NULL,
  `update_time` bigint DEFAULT NULL,
  `update_date` datetime DEFAULT NULL,
  `tenant_id` varchar(32) COLLATE utf8mb4_unicode_ci NOT NULL,
  `token` varchar(255) COLLATE utf8mb4_unicode_ci NOT NULL,
  `dialog_id` varchar(32) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `source` varchar(16) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `beta` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  PRIMARY KEY (`tenant_id`,`token`),
  KEY `apitoken_create_time` (`create_time`),
  KEY `apitoken_create_date` (`create_date`),
  KEY `apitoken_update_time` (`update_time`),
  KEY `apitoken_update_date` (`update_date`),
  KEY `apitoken_tenant_id` (`tenant_id`),
  KEY `apitoken_token` (`token`),
  KEY `apitoken_dialog_id` (`dialog_id`),
  KEY `apitoken_source` (`source`),
  KEY `apitoken_beta` (`beta`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `canvas_template` (
  `id` varchar(32) COLLATE utf8mb4_unicode_ci NOT NULL,
  `create_time` bigint DEFAULT NULL,
  `create_date` datetime DEFAULT NULL,
  `update_time` bigint DEFAULT NULL,
  `update_date` datetime DEFAULT NULL,
  `avatar` text COLLATE utf8mb4_unicode_ci,
  `title` longtext COLLATE utf8mb4_unicode_ci,
  `description` longtext COLLATE utf8mb4_unicode_ci,
  `canvas_type` varchar(32) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `canvas_category` varchar(32) COLLATE utf8mb4_unicode_ci NOT NULL,
  `dsl` longtext COLLATE utf8mb4_unicode_ci,
  PRIMARY KEY (`id`),
  KEY `canvastemplate_create_time` (`create_time`),
  KEY `canvastemplate_create_date` (`create_date`),
  KEY `canvastemplate_update_time` (`update_time`),
  KEY `canvastemplate_update_date` (`update_date`),
  KEY `canvastemplate_canvas_type` (`canvas_type`),
  KEY `canvastemplate_canvas_category` (`canvas_category`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `connector` (
  `id` varchar(32) COLLATE utf8mb4_unicode_ci NOT NULL,
  `create_time` bigint DEFAULT NULL,
  `create_date` datetime DEFAULT NULL,
  `update_time` bigint DEFAULT NULL,
  `update_date` datetime DEFAULT NULL,
  `tenant_id` varchar(32) COLLATE utf8mb4_unicode_ci NOT NULL,
  `name` varchar(128) COLLATE utf8mb4_unicode_ci NOT NULL,
  `source` varchar(128) COLLATE utf8mb4_unicode_ci NOT NULL,
  `input_type` varchar(128) COLLATE utf8mb4_unicode_ci NOT NULL,
  `config` longtext COLLATE utf8mb4_unicode_ci NOT NULL,
  `refresh_freq` int NOT NULL,
  `prune_freq` int NOT NULL,
  `timeout_secs` int NOT NULL,
  `indexing_start` datetime DEFAULT NULL,
  `status` varchar(16) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  PRIMARY KEY (`id`),
  KEY `connector_create_time` (`create_time`),
  KEY `connector_create_date` (`create_date`),
  KEY `connector_update_time` (`update_time`),
  KEY `connector_update_date` (`update_date`),
  KEY `connector_tenant_id` (`tenant_id`),
  KEY `connector_source` (`source`),
  KEY `connector_input_type` (`input_type`),
  KEY `connector_indexing_start` (`indexing_start`),
  KEY `connector_status` (`status`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `connector2kb` (
  `id` varchar(32) COLLATE utf8mb4_unicode_ci NOT NULL,
  `create_time` bigint DEFAULT NULL,
  `create_date` datetime DEFAULT NULL,
  `update_time` bigint DEFAULT NULL,
  `update_date` datetime DEFAULT NULL,
  `connector_id` varchar(32) COLLATE utf8mb4_unicode_ci NOT NULL,
  `kb_id` varchar(32) COLLATE utf8mb4_unicode_ci NOT NULL,
  `auto_parse` varchar(1) COLLATE utf8mb4_unicode_ci NOT NULL,
  PRIMARY KEY (`id`),
  KEY `connector2kb_create_time` (`create_time`),
  KEY `connector2kb_create_date` (`create_date`),
  KEY `connector2kb_update_time` (`update_time`),
  KEY `connector2kb_update_date` (`update_date`),
  KEY `connector2kb_connector_id` (`connector_id`),
  KEY `connector2kb_kb_id` (`kb_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `conversation` (
  `id` varchar(32) COLLATE utf8mb4_unicode_ci NOT NULL,
  `create_time` bigint DEFAULT NULL,
  `create_date` datetime DEFAULT NULL,
  `update_time` bigint DEFAULT NULL,
  `update_date` datetime DEFAULT NULL,
  `dialog_id` varchar(32) COLLATE utf8mb4_unicode_ci NOT NULL,
  `name` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `message` longtext COLLATE utf8mb4_unicode_ci,
  `reference` longtext COLLATE utf8mb4_unicode_ci,
  `user_id` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  PRIMARY KEY (`id`),
  KEY `conversation_create_time` (`create_time`),
  KEY `conversation_create_date` (`create_date`),
  KEY `conversation_update_time` (`update_time`),
  KEY `conversation_update_date` (`update_date`),
  KEY `conversation_dialog_id` (`dialog_id`),
  KEY `conversation_name` (`name`),
  KEY `conversation_user_id` (`user_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `dialog` (
  `id` varchar(32) COLLATE utf8mb4_unicode_ci NOT NULL,
  `create_time` bigint DEFAULT NULL,
  `create_date` datetime DEFAULT NULL,
  `update_time` bigint DEFAULT NULL,
  `update_date` datetime DEFAULT NULL,
  `tenant_id` varchar(32) COLLATE utf8mb4_unicode_ci NOT NULL,
  `name` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `description` text COLLATE utf8mb4_unicode_ci,
  `icon` text COLLATE utf8mb4_unicode_ci,
  `language` varchar(32) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `llm_id` varchar(128) COLLATE utf8mb4_unicode_ci NOT NULL,
  `llm_setting` longtext COLLATE utf8mb4_unicode_ci NOT NULL,
  `prompt_type` varchar(16) COLLATE utf8mb4_unicode_ci NOT NULL,
  `prompt_config` longtext COLLATE utf8mb4_unicode_ci NOT NULL,
  `meta_data_filter` longtext COLLATE utf8mb4_unicode_ci,
  `similarity_threshold` float NOT NULL,
  `vector_similarity_weight` float NOT NULL,
  `top_n` int NOT NULL,
  `top_k` int NOT NULL,
  `do_refer` varchar(1) COLLATE utf8mb4_unicode_ci NOT NULL,
  `rerank_id` varchar(128) COLLATE utf8mb4_unicode_ci NOT NULL,
  `kb_ids` longtext COLLATE utf8mb4_unicode_ci NOT NULL,
  `status` varchar(1) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  PRIMARY KEY (`id`),
  KEY `dialog_create_time` (`create_time`),
  KEY `dialog_create_date` (`create_date`),
  KEY `dialog_update_time` (`update_time`),
  KEY `dialog_update_date` (`update_date`),
  KEY `dialog_tenant_id` (`tenant_id`),
  KEY `dialog_name` (`name`),
  KEY `dialog_language` (`language`),
  KEY `dialog_prompt_type` (`prompt_type`),
  KEY `dialog_status` (`status`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `document` (
  `id` varchar(32) COLLATE utf8mb4_unicode_ci NOT NULL,
  `create_time` bigint DEFAULT NULL,
  `create_date` datetime DEFAULT NULL,
  `update_time` bigint DEFAULT NULL,
  `update_date` datetime DEFAULT NULL,
  `thumbnail` text COLLATE utf8mb4_unicode_ci,
  `kb_id` varchar(256) COLLATE utf8mb4_unicode_ci NOT NULL,
  `parser_id` varchar(32) COLLATE utf8mb4_unicode_ci NOT NULL,
  `pipeline_id` varchar(32) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `parser_config` longtext COLLATE utf8mb4_unicode_ci NOT NULL,
  `source_type` varchar(128) COLLATE utf8mb4_unicode_ci NOT NULL,
  `type` varchar(32) COLLATE utf8mb4_unicode_ci NOT NULL,
  `created_by` varchar(32) COLLATE utf8mb4_unicode_ci NOT NULL,
  `name` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `location` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `size` int NOT NULL,
  `token_num` int NOT NULL,
  `chunk_num` int NOT NULL,
  `progress` float NOT NULL,
  `progress_msg` text COLLATE utf8mb4_unicode_ci,
  `process_begin_at` datetime DEFAULT NULL,
  `process_duration` float NOT NULL,
  `suffix` varchar(32) COLLATE utf8mb4_unicode_ci NOT NULL,
  `run` varchar(1) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `status` varchar(1) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  PRIMARY KEY (`id`),
  KEY `document_create_time` (`create_time`),
  KEY `document_create_date` (`create_date`),
  KEY `document_update_time` (`update_time`),
  KEY `document_update_date` (`update_date`),
  KEY `document_kb_id` (`kb_id`),
  KEY `document_parser_id` (`parser_id`),
  KEY `document_pipeline_id` (`pipeline_id`),
  KEY `document_source_type` (`source_type`),
  KEY `document_type` (`type`),
  KEY `document_created_by` (`created_by`),
  KEY `document_name` (`name`),
  KEY `document_location` (`location`),
  KEY `document_size` (`size`),
  KEY `document_token_num` (`token_num`),
  KEY `document_chunk_num` (`chunk_num`),
  KEY `document_progress` (`progress`),
  KEY `document_process_begin_at` (`process_begin_at`),
  KEY `document_suffix` (`suffix`),
  KEY `document_run` (`run`),
  KEY `document_status` (`status`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `evaluation_cases` (
  `id` varchar(32) COLLATE utf8mb4_unicode_ci NOT NULL,
  `create_date` datetime DEFAULT NULL,
  `update_time` bigint DEFAULT NULL,
  `update_date` datetime DEFAULT NULL,
  `dataset_id` varchar(32) COLLATE utf8mb4_unicode_ci NOT NULL,
  `question` text COLLATE utf8mb4_unicode_ci NOT NULL,
  `reference_answer` text COLLATE utf8mb4_unicode_ci,
  `relevant_doc_ids` longtext COLLATE utf8mb4_unicode_ci,
  `relevant_chunk_ids` longtext COLLATE utf8mb4_unicode_ci,
  `metadata` longtext COLLATE utf8mb4_unicode_ci,
  `create_time` bigint NOT NULL,
  PRIMARY KEY (`id`),
  KEY `evaluationcase_create_date` (`create_date`),
  KEY `evaluationcase_update_time` (`update_time`),
  KEY `evaluationcase_update_date` (`update_date`),
  KEY `evaluationcase_dataset_id` (`dataset_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `evaluation_datasets` (
  `id` varchar(32) COLLATE utf8mb4_unicode_ci NOT NULL,
  `create_date` datetime DEFAULT NULL,
  `update_date` datetime DEFAULT NULL,
  `tenant_id` varchar(32) COLLATE utf8mb4_unicode_ci NOT NULL,
  `name` varchar(255) COLLATE utf8mb4_unicode_ci NOT NULL,
  `description` text COLLATE utf8mb4_unicode_ci,
  `kb_ids` longtext COLLATE utf8mb4_unicode_ci NOT NULL,
  `created_by` varchar(32) COLLATE utf8mb4_unicode_ci NOT NULL,
  `create_time` bigint NOT NULL,
  `update_time` bigint NOT NULL,
  `status` int NOT NULL,
  PRIMARY KEY (`id`),
  KEY `evaluationdataset_create_date` (`create_date`),
  KEY `evaluationdataset_update_date` (`update_date`),
  KEY `evaluationdataset_tenant_id` (`tenant_id`),
  KEY `evaluationdataset_name` (`name`),
  KEY `evaluationdataset_created_by` (`created_by`),
  KEY `evaluationdataset_create_time` (`create_time`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `evaluation_results` (
  `id` varchar(32) COLLATE utf8mb4_unicode_ci NOT NULL,
  `create_date` datetime DEFAULT NULL,
  `update_time` bigint DEFAULT NULL,
  `update_date` datetime DEFAULT NULL,
  `run_id` varchar(32) COLLATE utf8mb4_unicode_ci NOT NULL,
  `case_id` varchar(32) COLLATE utf8mb4_unicode_ci NOT NULL,
  `generated_answer` text COLLATE utf8mb4_unicode_ci NOT NULL,
  `retrieved_chunks` longtext COLLATE utf8mb4_unicode_ci NOT NULL,
  `metrics` longtext COLLATE utf8mb4_unicode_ci NOT NULL,
  `execution_time` float NOT NULL,
  `token_usage` longtext COLLATE utf8mb4_unicode_ci,
  `create_time` bigint NOT NULL,
  PRIMARY KEY (`id`),
  KEY `evaluationresult_create_date` (`create_date`),
  KEY `evaluationresult_update_time` (`update_time`),
  KEY `evaluationresult_update_date` (`update_date`),
  KEY `evaluationresult_run_id` (`run_id`),
  KEY `evaluationresult_case_id` (`case_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `evaluation_runs` (
  `id` varchar(32) COLLATE utf8mb4_unicode_ci NOT NULL,
  `create_date` datetime DEFAULT NULL,
  `update_time` bigint DEFAULT NULL,
  `update_date` datetime DEFAULT NULL,
  `dataset_id` varchar(32) COLLATE utf8mb4_unicode_ci NOT NULL,
  `dialog_id` varchar(32) COLLATE utf8mb4_unicode_ci NOT NULL,
  `name` varchar(255) COLLATE utf8mb4_unicode_ci NOT NULL,
  `config_snapshot` longtext COLLATE utf8mb4_unicode_ci NOT NULL,
  `metrics_summary` longtext COLLATE utf8mb4_unicode_ci,
  `status` varchar(32) COLLATE utf8mb4_unicode_ci NOT NULL,
  `created_by` varchar(32) COLLATE utf8mb4_unicode_ci NOT NULL,
  `create_time` bigint NOT NULL,
  `complete_time` bigint DEFAULT NULL,
  PRIMARY KEY (`id`),
  KEY `evaluationrun_create_date` (`create_date`),
  KEY `evaluationrun_update_time` (`update_time`),
  KEY `evaluationrun_update_date` (`update_date`),
  KEY `evaluationrun_dataset_id` (`dataset_id`),
  KEY `evaluationrun_dialog_id` (`dialog_id`),
  KEY `evaluationrun_created_by` (`created_by`),
  KEY `evaluationrun_create_time` (`create_time`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `file` (
  `id` varchar(32) COLLATE utf8mb4_unicode_ci NOT NULL,
  `create_time` bigint DEFAULT NULL,
  `create_date` datetime DEFAULT NULL,
  `update_time` bigint DEFAULT NULL,
  `update_date` datetime DEFAULT NULL,
  `parent_id` varchar(32) COLLATE utf8mb4_unicode_ci NOT NULL,
  `tenant_id` varchar(32) COLLATE utf8mb4_unicode_ci NOT NULL,
  `created_by` varchar(32) COLLATE utf8mb4_unicode_ci NOT NULL,
  `name` varchar(255) COLLATE utf8mb4_unicode_ci NOT NULL,
  `location` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `size` int NOT NULL,
  `type` varchar(32) COLLATE utf8mb4_unicode_ci NOT NULL,
  `source_type` varchar(128) COLLATE utf8mb4_unicode_ci NOT NULL,
  PRIMARY KEY (`id`),
  KEY `file_create_time` (`create_time`),
  KEY `file_create_date` (`create_date`),
  KEY `file_update_time` (`update_time`),
  KEY `file_update_date` (`update_date`),
  KEY `file_parent_id` (`parent_id`),
  KEY `file_tenant_id` (`tenant_id`),
  KEY `file_created_by` (`created_by`),
  KEY `file_name` (`name`),
  KEY `file_location` (`location`),
  KEY `file_size` (`size`),
  KEY `file_type` (`type`),
  KEY `file_source_type` (`source_type`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `file2document` (
  `id` varchar(32) COLLATE utf8mb4_unicode_ci NOT NULL,
  `create_time` bigint DEFAULT NULL,
  `create_date` datetime DEFAULT NULL,
  `update_time` bigint DEFAULT NULL,
  `update_date` datetime DEFAULT NULL,
  `file_id` varchar(32) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `document_id` varchar(32) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  PRIMARY KEY (`id`),
  KEY `file2document_create_time` (`create_time`),
  KEY `file2document_create_date` (`create_date`),
  KEY `file2document_update_time` (`update_time`),
  KEY `file2document_update_date` (`update_date`),
  KEY `file2document_file_id` (`file_id`),
  KEY `file2document_document_id` (`document_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `invitation_code` (
  `id` varchar(32) COLLATE utf8mb4_unicode_ci NOT NULL,
  `create_time` bigint DEFAULT NULL,
  `create_date` datetime DEFAULT NULL,
  `update_time` bigint DEFAULT NULL,
  `update_date` datetime DEFAULT NULL,
  `code` varchar(32) COLLATE utf8mb4_unicode_ci NOT NULL,
  `visit_time` datetime DEFAULT NULL,
  `user_id` varchar(32) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `tenant_id` varchar(32) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `status` varchar(1) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  PRIMARY KEY (`id`),
  KEY `invitationcode_create_time` (`create_time`),
  KEY `invitationcode_create_date` (`create_date`),
  KEY `invitationcode_update_time` (`update_time`),
  KEY `invitationcode_update_date` (`update_date`),
  KEY `invitationcode_code` (`code`),
  KEY `invitationcode_visit_time` (`visit_time`),
  KEY `invitationcode_user_id` (`user_id`),
  KEY `invitationcode_tenant_id` (`tenant_id`),
  KEY `invitationcode_status` (`status`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `knowledgebase` (
  `id` varchar(32) COLLATE utf8mb4_unicode_ci NOT NULL,
  `create_time` bigint DEFAULT NULL,
  `create_date` datetime DEFAULT NULL,
  `update_time` bigint DEFAULT NULL,
  `update_date` datetime DEFAULT NULL,
  `avatar` text COLLATE utf8mb4_unicode_ci,
  `tenant_id` varchar(32) COLLATE utf8mb4_unicode_ci NOT NULL,
  `name` varchar(128) COLLATE utf8mb4_unicode_ci NOT NULL,
  `language` varchar(32) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `description` text COLLATE utf8mb4_unicode_ci,
  `embd_id` varchar(128) COLLATE utf8mb4_unicode_ci NOT NULL,
  `permission` varchar(16) COLLATE utf8mb4_unicode_ci NOT NULL,
  `created_by` varchar(32) COLLATE utf8mb4_unicode_ci NOT NULL,
  `doc_num` int NOT NULL,
  `token_num` int NOT NULL,
  `chunk_num` int NOT NULL,
  `similarity_threshold` float NOT NULL,
  `vector_similarity_weight` float NOT NULL,
  `parser_id` varchar(32) COLLATE utf8mb4_unicode_ci NOT NULL,
  `pipeline_id` varchar(32) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `parser_config` longtext COLLATE utf8mb4_unicode_ci NOT NULL,
  `pagerank` int NOT NULL,
  `graphrag_task_id` varchar(32) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `graphrag_task_finish_at` datetime DEFAULT NULL,
  `raptor_task_id` varchar(32) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `raptor_task_finish_at` datetime DEFAULT NULL,
  `mindmap_task_id` varchar(32) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `mindmap_task_finish_at` datetime DEFAULT NULL,
  `status` varchar(1) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  PRIMARY KEY (`id`),
  KEY `knowledgebase_create_time` (`create_time`),
  KEY `knowledgebase_create_date` (`create_date`),
  KEY `knowledgebase_update_time` (`update_time`),
  KEY `knowledgebase_update_date` (`update_date`),
  KEY `knowledgebase_tenant_id` (`tenant_id`),
  KEY `knowledgebase_name` (`name`),
  KEY `knowledgebase_language` (`language`),
  KEY `knowledgebase_embd_id` (`embd_id`),
  KEY `knowledgebase_permission` (`permission`),
  KEY `knowledgebase_created_by` (`created_by`),
  KEY `knowledgebase_doc_num` (`doc_num`),
  KEY `knowledgebase_token_num` (`token_num`),
  KEY `knowledgebase_chunk_num` (`chunk_num`),
  KEY `knowledgebase_similarity_threshold` (`similarity_threshold`),
  KEY `knowledgebase_vector_similarity_weight` (`vector_similarity_weight`),
  KEY `knowledgebase_parser_id` (`parser_id`),
  KEY `knowledgebase_pipeline_id` (`pipeline_id`),
  KEY `knowledgebase_graphrag_task_id` (`graphrag_task_id`),
  KEY `knowledgebase_raptor_task_id` (`raptor_task_id`),
  KEY `knowledgebase_mindmap_task_id` (`mindmap_task_id`),
  KEY `knowledgebase_status` (`status`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `llm` (
  `create_time` bigint DEFAULT NULL,
  `create_date` datetime DEFAULT NULL,
  `update_time` bigint DEFAULT NULL,
  `update_date` datetime DEFAULT NULL,
  `llm_name` varchar(128) COLLATE utf8mb4_unicode_ci NOT NULL,
  `model_type` varchar(128) COLLATE utf8mb4_unicode_ci NOT NULL,
  `fid` varchar(128) COLLATE utf8mb4_unicode_ci NOT NULL,
  `max_tokens` int NOT NULL,
  `tags` varchar(255) COLLATE utf8mb4_unicode_ci NOT NULL,
  `is_tools` tinyint(1) NOT NULL,
  `status` varchar(1) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  PRIMARY KEY (`fid`,`llm_name`),
  KEY `llm_create_time` (`create_time`),
  KEY `llm_create_date` (`create_date`),
  KEY `llm_update_time` (`update_time`),
  KEY `llm_update_date` (`update_date`),
  KEY `llm_llm_name` (`llm_name`),
  KEY `llm_model_type` (`model_type`),
  KEY `llm_fid` (`fid`),
  KEY `llm_tags` (`tags`),
  KEY `llm_status` (`status`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `llm_factories` (
  `name` varchar(128) COLLATE utf8mb4_unicode_ci NOT NULL,
  `create_time` bigint DEFAULT NULL,
  `create_date` datetime DEFAULT NULL,
  `update_time` bigint DEFAULT NULL,
  `update_date` datetime DEFAULT NULL,
  `logo` text COLLATE utf8mb4_unicode_ci,
  `tags` varchar(255) COLLATE utf8mb4_unicode_ci NOT NULL,
  `rank` int NOT NULL,
  `status` varchar(1) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  PRIMARY KEY (`name`),
  KEY `llmfactories_create_time` (`create_time`),
  KEY `llmfactories_create_date` (`create_date`),
  KEY `llmfactories_update_time` (`update_time`),
  KEY `llmfactories_update_date` (`update_date`),
  KEY `llmfactories_tags` (`tags`),
  KEY `llmfactories_status` (`status`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `mcp_server` (
  `id` varchar(32) COLLATE utf8mb4_unicode_ci NOT NULL,
  `create_time` bigint DEFAULT NULL,
  `create_date` datetime DEFAULT NULL,
  `update_time` bigint DEFAULT NULL,
  `update_date` datetime DEFAULT NULL,
  `name` varchar(255) COLLATE utf8mb4_unicode_ci NOT NULL,
  `tenant_id` varchar(32) COLLATE utf8mb4_unicode_ci NOT NULL,
  `url` varchar(2048) COLLATE utf8mb4_unicode_ci NOT NULL,
  `server_type` varchar(32) COLLATE utf8mb4_unicode_ci NOT NULL,
  `description` text COLLATE utf8mb4_unicode_ci,
  `variables` longtext COLLATE utf8mb4_unicode_ci,
  `headers` longtext COLLATE utf8mb4_unicode_ci,
  PRIMARY KEY (`id`),
  KEY `mcpserver_create_time` (`create_time`),
  KEY `mcpserver_create_date` (`create_date`),
  KEY `mcpserver_update_time` (`update_time`),
  KEY `mcpserver_update_date` (`update_date`),
  KEY `mcpserver_tenant_id` (`tenant_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `memory` (
  `id` varchar(32) COLLATE utf8mb4_unicode_ci NOT NULL,
  `create_time` bigint DEFAULT NULL,
  `create_date` datetime DEFAULT NULL,
  `update_time` bigint DEFAULT NULL,
  `update_date` datetime DEFAULT NULL,
  `name` varchar(128) COLLATE utf8mb4_unicode_ci NOT NULL,
  `avatar` text COLLATE utf8mb4_unicode_ci,
  `tenant_id` varchar(32) COLLATE utf8mb4_unicode_ci NOT NULL,
  `memory_type` int NOT NULL,
  `storage_type` varchar(32) COLLATE utf8mb4_unicode_ci NOT NULL,
  `embd_id` varchar(128) COLLATE utf8mb4_unicode_ci NOT NULL,
  `llm_id` varchar(128) COLLATE utf8mb4_unicode_ci NOT NULL,
  `permissions` varchar(16) COLLATE utf8mb4_unicode_ci NOT NULL,
  `description` text COLLATE utf8mb4_unicode_ci,
  `memory_size` int NOT NULL,
  `forgetting_policy` varchar(32) COLLATE utf8mb4_unicode_ci NOT NULL,
  `temperature` float NOT NULL,
  `system_prompt` text COLLATE utf8mb4_unicode_ci,
  `user_prompt` text COLLATE utf8mb4_unicode_ci,
  PRIMARY KEY (`id`),
  KEY `memory_create_time` (`create_time`),
  KEY `memory_create_date` (`create_date`),
  KEY `memory_update_time` (`update_time`),
  KEY `memory_update_date` (`update_date`),
  KEY `memory_tenant_id` (`tenant_id`),
  KEY `memory_memory_type` (`memory_type`),
  KEY `memory_storage_type` (`storage_type`),
  KEY `memory_permissions` (`permissions`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `pipeline_operation_log` (
  `id` varchar(32) COLLATE utf8mb4_unicode_ci NOT NULL,
  `create_time` bigint DEFAULT NULL,
  `create_date` datetime DEFAULT NULL,
  `update_time` bigint DEFAULT NULL,
  `update_date` datetime DEFAULT NULL,
  `document_id` varchar(32) COLLATE utf8mb4_unicode_ci NOT NULL,
  `tenant_id` varchar(32) COLLATE utf8mb4_unicode_ci NOT NULL,
  `kb_id` varchar(32) COLLATE utf8mb4_unicode_ci NOT NULL,
  `pipeline_id` varchar(32) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `pipeline_title` varchar(32) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `parser_id` varchar(32) COLLATE utf8mb4_unicode_ci NOT NULL,
  `document_name` varchar(255) COLLATE utf8mb4_unicode_ci NOT NULL,
  `document_suffix` varchar(255) COLLATE utf8mb4_unicode_ci NOT NULL,
  `document_type` varchar(255) COLLATE utf8mb4_unicode_ci NOT NULL,
  `source_from` varchar(255) COLLATE utf8mb4_unicode_ci NOT NULL,
  `progress` float NOT NULL,
  `progress_msg` text COLLATE utf8mb4_unicode_ci,
  `process_begin_at` datetime DEFAULT NULL,
  `process_duration` float NOT NULL,
  `dsl` longtext COLLATE utf8mb4_unicode_ci,
  `task_type` varchar(32) COLLATE utf8mb4_unicode_ci NOT NULL,
  `operation_status` varchar(32) COLLATE utf8mb4_unicode_ci NOT NULL,
  `avatar` text COLLATE utf8mb4_unicode_ci,
  `status` varchar(1) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  PRIMARY KEY (`id`),
  KEY `pipelineoperationlog_create_time` (`create_time`),
  KEY `pipelineoperationlog_create_date` (`create_date`),
  KEY `pipelineoperationlog_update_time` (`update_time`),
  KEY `pipelineoperationlog_update_date` (`update_date`),
  KEY `pipelineoperationlog_document_id` (`document_id`),
  KEY `pipelineoperationlog_tenant_id` (`tenant_id`),
  KEY `pipelineoperationlog_kb_id` (`kb_id`),
  KEY `pipelineoperationlog_pipeline_id` (`pipeline_id`),
  KEY `pipelineoperationlog_pipeline_title` (`pipeline_title`),
  KEY `pipelineoperationlog_parser_id` (`parser_id`),
  KEY `pipelineoperationlog_progress` (`progress`),
  KEY `pipelineoperationlog_process_begin_at` (`process_begin_at`),
  KEY `pipelineoperationlog_status` (`status`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `search` (
  `id` varchar(32) COLLATE utf8mb4_unicode_ci NOT NULL,
  `create_time` bigint DEFAULT NULL,
  `create_date` datetime DEFAULT NULL,
  `update_time` bigint DEFAULT NULL,
  `update_date` datetime DEFAULT NULL,
  `avatar` text COLLATE utf8mb4_unicode_ci,
  `tenant_id` varchar(32) COLLATE utf8mb4_unicode_ci NOT NULL,
  `name` varchar(128) COLLATE utf8mb4_unicode_ci NOT NULL,
  `description` text COLLATE utf8mb4_unicode_ci,
  `created_by` varchar(32) COLLATE utf8mb4_unicode_ci NOT NULL,
  `search_config` longtext COLLATE utf8mb4_unicode_ci NOT NULL,
  `status` varchar(1) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  PRIMARY KEY (`id`),
  KEY `search_create_time` (`create_time`),
  KEY `search_create_date` (`create_date`),
  KEY `search_update_time` (`update_time`),
  KEY `search_update_date` (`update_date`),
  KEY `search_tenant_id` (`tenant_id`),
  KEY `search_name` (`name`),
  KEY `search_created_by` (`created_by`),
  KEY `search_status` (`status`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `sync_logs` (
  `id` varchar(32) COLLATE utf8mb4_unicode_ci NOT NULL,
  `create_time` bigint DEFAULT NULL,
  `create_date` datetime DEFAULT NULL,
  `update_time` bigint DEFAULT NULL,
  `update_date` datetime DEFAULT NULL,
  `connector_id` varchar(32) COLLATE utf8mb4_unicode_ci NOT NULL,
  `status` varchar(128) COLLATE utf8mb4_unicode_ci NOT NULL,
  `from_beginning` varchar(1) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `new_docs_indexed` int NOT NULL,
  `total_docs_indexed` int NOT NULL,
  `docs_removed_from_index` int NOT NULL,
  `error_msg` text COLLATE utf8mb4_unicode_ci NOT NULL,
  `error_count` int NOT NULL,
  `full_exception_trace` text COLLATE utf8mb4_unicode_ci,
  `time_started` datetime DEFAULT NULL,
  `poll_range_start` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `poll_range_end` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `kb_id` varchar(32) COLLATE utf8mb4_unicode_ci NOT NULL,
  PRIMARY KEY (`id`),
  KEY `synclogs_create_time` (`create_time`),
  KEY `synclogs_create_date` (`create_date`),
  KEY `synclogs_update_time` (`update_time`),
  KEY `synclogs_update_date` (`update_date`),
  KEY `synclogs_connector_id` (`connector_id`),
  KEY `synclogs_status` (`status`),
  KEY `synclogs_time_started` (`time_started`),
  KEY `synclogs_poll_range_start` (`poll_range_start`),
  KEY `synclogs_poll_range_end` (`poll_range_end`),
  KEY `synclogs_kb_id` (`kb_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `system_settings` (
  `name` varchar(128) COLLATE utf8mb4_unicode_ci NOT NULL,
  `create_time` bigint DEFAULT NULL,
  `create_date` datetime DEFAULT NULL,
  `update_time` bigint DEFAULT NULL,
  `update_date` datetime DEFAULT NULL,
  `source` varchar(32) COLLATE utf8mb4_unicode_ci NOT NULL,
  `data_type` varchar(32) COLLATE utf8mb4_unicode_ci NOT NULL,
  `value` text COLLATE utf8mb4_unicode_ci NOT NULL,
  PRIMARY KEY (`name`),
  KEY `systemsettings_create_time` (`create_time`),
  KEY `systemsettings_create_date` (`create_date`),
  KEY `systemsettings_update_time` (`update_time`),
  KEY `systemsettings_update_date` (`update_date`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `task` (
  `id` varchar(32) COLLATE utf8mb4_unicode_ci NOT NULL,
  `create_time` bigint DEFAULT NULL,
  `create_date` datetime DEFAULT NULL,
  `update_time` bigint DEFAULT NULL,
  `update_date` datetime DEFAULT NULL,
  `doc_id` varchar(32) COLLATE utf8mb4_unicode_ci NOT NULL,
  `from_page` int NOT NULL,
  `to_page` int NOT NULL,
  `task_type` varchar(32) COLLATE utf8mb4_unicode_ci NOT NULL,
  `priority` int NOT NULL,
  `begin_at` datetime DEFAULT NULL,
  `process_duration` float NOT NULL,
  `progress` float NOT NULL,
  `progress_msg` text COLLATE utf8mb4_unicode_ci,
  `retry_count` int NOT NULL,
  `digest` text COLLATE utf8mb4_unicode_ci,
  `chunk_ids` longtext COLLATE utf8mb4_unicode_ci,
  PRIMARY KEY (`id`),
  KEY `task_create_time` (`create_time`),
  KEY `task_create_date` (`create_date`),
  KEY `task_update_time` (`update_time`),
  KEY `task_update_date` (`update_date`),
  KEY `task_doc_id` (`doc_id`),
  KEY `task_begin_at` (`begin_at`),
  KEY `task_progress` (`progress`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `tenant` (
  `id` varchar(32) COLLATE utf8mb4_unicode_ci NOT NULL,
  `create_time` bigint DEFAULT NULL,
  `create_date` datetime DEFAULT NULL,
  `update_time` bigint DEFAULT NULL,
  `update_date` datetime DEFAULT NULL,
  `name` varchar(100) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `public_key` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `llm_id` varchar(128) COLLATE utf8mb4_unicode_ci NOT NULL,
  `embd_id` varchar(128) COLLATE utf8mb4_unicode_ci NOT NULL,
  `asr_id` varchar(128) COLLATE utf8mb4_unicode_ci NOT NULL,
  `img2txt_id` varchar(128) COLLATE utf8mb4_unicode_ci NOT NULL,
  `rerank_id` varchar(128) COLLATE utf8mb4_unicode_ci NOT NULL,
  `tts_id` varchar(256) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `parser_ids` varchar(256) COLLATE utf8mb4_unicode_ci NOT NULL,
  `credit` int NOT NULL,
  `status` varchar(1) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  PRIMARY KEY (`id`),
  KEY `tenant_create_time` (`create_time`),
  KEY `tenant_create_date` (`create_date`),
  KEY `tenant_update_time` (`update_time`),
  KEY `tenant_update_date` (`update_date`),
  KEY `tenant_name` (`name`),
  KEY `tenant_public_key` (`public_key`),
  KEY `tenant_llm_id` (`llm_id`),
  KEY `tenant_embd_id` (`embd_id`),
  KEY `tenant_asr_id` (`asr_id`),
  KEY `tenant_img2txt_id` (`img2txt_id`),
  KEY `tenant_rerank_id` (`rerank_id`),
  KEY `tenant_tts_id` (`tts_id`),
  KEY `tenant_parser_ids` (`parser_ids`),
  KEY `tenant_credit` (`credit`),
  KEY `tenant_status` (`status`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `tenant_langfuse` (
  `tenant_id` varchar(32) COLLATE utf8mb4_unicode_ci NOT NULL,
  `create_time` bigint DEFAULT NULL,
  `create_date` datetime DEFAULT NULL,
  `update_time` bigint DEFAULT NULL,
  `update_date` datetime DEFAULT NULL,
  `secret_key` varchar(2048) COLLATE utf8mb4_unicode_ci NOT NULL,
  `public_key` varchar(2048) COLLATE utf8mb4_unicode_ci NOT NULL,
  `host` varchar(128) COLLATE utf8mb4_unicode_ci NOT NULL,
  PRIMARY KEY (`tenant_id`),
  KEY `tenantlangfuse_create_time` (`create_time`),
  KEY `tenantlangfuse_create_date` (`create_date`),
  KEY `tenantlangfuse_update_time` (`update_time`),
  KEY `tenantlangfuse_update_date` (`update_date`),
  KEY `tenantlangfuse_secret_key` (`secret_key`(768)),
  KEY `tenantlangfuse_public_key` (`public_key`(768)),
  KEY `tenantlangfuse_host` (`host`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `tenant_llm` (
  `create_time` bigint DEFAULT NULL,
  `create_date` datetime DEFAULT NULL,
  `update_time` bigint DEFAULT NULL,
  `update_date` datetime DEFAULT NULL,
  `tenant_id` varchar(32) COLLATE utf8mb4_unicode_ci NOT NULL,
  `llm_factory` varchar(128) COLLATE utf8mb4_unicode_ci NOT NULL,
  `model_type` varchar(128) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `llm_name` varchar(128) COLLATE utf8mb4_unicode_ci NOT NULL,
  `api_key` text COLLATE utf8mb4_unicode_ci,
  `api_base` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `max_tokens` int NOT NULL,
  `used_tokens` int NOT NULL,
  `status` varchar(1) COLLATE utf8mb4_unicode_ci NOT NULL,
  PRIMARY KEY (`tenant_id`,`llm_factory`,`llm_name`),
  KEY `tenantllm_create_time` (`create_time`),
  KEY `tenantllm_create_date` (`create_date`),
  KEY `tenantllm_update_time` (`update_time`),
  KEY `tenantllm_update_date` (`update_date`),
  KEY `tenantllm_tenant_id` (`tenant_id`),
  KEY `tenantllm_llm_factory` (`llm_factory`),
  KEY `tenantllm_model_type` (`model_type`),
  KEY `tenantllm_llm_name` (`llm_name`),
  KEY `tenantllm_max_tokens` (`max_tokens`),
  KEY `tenantllm_used_tokens` (`used_tokens`),
  KEY `tenantllm_status` (`status`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `user` (
  `id` varchar(32) COLLATE utf8mb4_unicode_ci NOT NULL,
  `create_time` bigint DEFAULT NULL,
  `create_date` datetime DEFAULT NULL,
  `update_time` bigint DEFAULT NULL,
  `update_date` datetime DEFAULT NULL,
  `access_token` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `nickname` varchar(100) COLLATE utf8mb4_unicode_ci NOT NULL,
  `password` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `email` varchar(255) COLLATE utf8mb4_unicode_ci NOT NULL,
  `avatar` text COLLATE utf8mb4_unicode_ci,
  `language` varchar(32) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `color_schema` varchar(32) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `timezone` varchar(64) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `last_login_time` datetime DEFAULT NULL,
  `is_authenticated` varchar(1) COLLATE utf8mb4_unicode_ci NOT NULL,
  `is_active` varchar(1) COLLATE utf8mb4_unicode_ci NOT NULL,
  `is_anonymous` varchar(1) COLLATE utf8mb4_unicode_ci NOT NULL,
  `login_channel` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `status` varchar(1) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `is_superuser` tinyint(1) DEFAULT NULL,
  PRIMARY KEY (`id`),
  KEY `user_create_time` (`create_time`),
  KEY `user_create_date` (`create_date`),
  KEY `user_update_time` (`update_time`),
  KEY `user_update_date` (`update_date`),
  KEY `user_access_token` (`access_token`),
  KEY `user_nickname` (`nickname`),
  KEY `user_password` (`password`),
  KEY `user_email` (`email`),
  KEY `user_language` (`language`),
  KEY `user_color_schema` (`color_schema`),
  KEY `user_timezone` (`timezone`),
  KEY `user_last_login_time` (`last_login_time`),
  KEY `user_is_authenticated` (`is_authenticated`),
  KEY `user_is_active` (`is_active`),
  KEY `user_is_anonymous` (`is_anonymous`),
  KEY `user_login_channel` (`login_channel`),
  KEY `user_status` (`status`),
  KEY `user_is_superuser` (`is_superuser`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `user_canvas` (
  `id` varchar(32) COLLATE utf8mb4_unicode_ci NOT NULL,
  `create_time` bigint DEFAULT NULL,
  `create_date` datetime DEFAULT NULL,
  `update_time` bigint DEFAULT NULL,
  `update_date` datetime DEFAULT NULL,
  `avatar` text COLLATE utf8mb4_unicode_ci,
  `user_id` varchar(255) COLLATE utf8mb4_unicode_ci NOT NULL,
  `title` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `permission` varchar(16) COLLATE utf8mb4_unicode_ci NOT NULL,
  `description` text COLLATE utf8mb4_unicode_ci,
  `canvas_type` varchar(32) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `canvas_category` varchar(32) COLLATE utf8mb4_unicode_ci NOT NULL,
  `dsl` longtext COLLATE utf8mb4_unicode_ci,
  PRIMARY KEY (`id`),
  KEY `usercanvas_create_time` (`create_time`),
  KEY `usercanvas_create_date` (`create_date`),
  KEY `usercanvas_update_time` (`update_time`),
  KEY `usercanvas_update_date` (`update_date`),
  KEY `usercanvas_user_id` (`user_id`),
  KEY `usercanvas_permission` (`permission`),
  KEY `usercanvas_canvas_type` (`canvas_type`),
  KEY `usercanvas_canvas_category` (`canvas_category`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `user_canvas_version` (
  `id` varchar(32) COLLATE utf8mb4_unicode_ci NOT NULL,
  `create_time` bigint DEFAULT NULL,
  `create_date` datetime DEFAULT NULL,
  `update_time` bigint DEFAULT NULL,
  `update_date` datetime DEFAULT NULL,
  `user_canvas_id` varchar(255) COLLATE utf8mb4_unicode_ci NOT NULL,
  `title` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `description` text COLLATE utf8mb4_unicode_ci,
  `dsl` longtext COLLATE utf8mb4_unicode_ci,
  PRIMARY KEY (`id`),
  KEY `usercanvasversion_create_time` (`create_time`),
  KEY `usercanvasversion_create_date` (`create_date`),
  KEY `usercanvasversion_update_time` (`update_time`),
  KEY `usercanvasversion_update_date` (`update_date`),
  KEY `usercanvasversion_user_canvas_id` (`user_canvas_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `user_tenant` (
  `id` varchar(32) COLLATE utf8mb4_unicode_ci NOT NULL,
  `create_time` bigint DEFAULT NULL,
  `create_date` datetime DEFAULT NULL,
  `update_time` bigint DEFAULT NULL,
  `update_date` datetime DEFAULT NULL,
  `user_id` varchar(32) COLLATE utf8mb4_unicode_ci NOT NULL,
  `tenant_id` varchar(32) COLLATE utf8mb4_unicode_ci NOT NULL,
  `role` varchar(32) COLLATE utf8mb4_unicode_ci NOT NULL,
  `invited_by` varchar(32) COLLATE utf8mb4_unicode_ci NOT NULL,
  `status` varchar(1) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  PRIMARY KEY (`id`),
  KEY `usertenant_create_time` (`create_time`),
  KEY `usertenant_create_date` (`create_date`),
  KEY `usertenant_update_time` (`update_time`),
  KEY `usertenant_update_date` (`update_date`),
  KEY `usertenant_user_id` (`user_id`),
  KEY `usertenant_tenant_id` (`tenant_id`),
  KEY `usertenant_role` (`role`),
  KEY `usertenant_invited_by` (`invited_by`),
  KEY `usertenant_status` (`status`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
/*!40103 SET TIME_ZONE=@OLD_TIME_ZONE */;

/*!40101 SET SQL_MODE=@OLD_SQL_MODE */;
/*!40014 SET FOREIGN_KEY_CHECKS=@OLD_FOREIGN_KEY_CHECKS */;
/*!40014 SET UNIQUE_CHECKS=@OLD_UNIQUE_CHECKS */;
/*!40101 SET CHARACTER_SET_CLIENT=@OLD_CHARACTER_SET_CLIENT */;
/*!40101 SET CHARACTER_SET_RESULTS=@OLD_CHARACTER_SET_RESULTS */;
/*!40101 SET COLLATION_CONNECTION=@OLD_COLLATION_CONNECTION */;
/*!40111 SET SQL_NOTES=@OLD_SQL_NOTES */;


--
-- Tabele ai_hub_* (projekt hub-compat) — przepisane z TypeScript na MySQL.
-- Pliki źródłowe (tylko odczyt):
--   ../hub-compat/raglow-service/ragflow-user-api/src/services/migrations.ts
--   ../hub-compat/raglow-service/sharepoint-sync/src/services/migrations.ts
--

/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `ai_hub_user_assistant_access` (
  `email` varchar(255) NOT NULL,
  `dialog_id` varchar(32) NOT NULL,
  `created_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `created_by` varchar(255) DEFAULT NULL,
  PRIMARY KEY (`email`,`dialog_id`),
  KEY `idx_ai_hub_uaa_email` (`email`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `ai_hub_sharepoint_integrations` (
  `id` int NOT NULL AUTO_INCREMENT,
  `name` varchar(255) NOT NULL,
  `dataset_id` varchar(64) NOT NULL,
  `tenant_id` varchar(64) NOT NULL,
  `client_id` varchar(64) NOT NULL,
  `client_secret_encrypted` text NOT NULL,
  `site_url` varchar(512) NOT NULL,
  `site_id` varchar(255) NOT NULL,
  `excluded_library_names` json NOT NULL,
  `max_file_size_bytes` bigint NOT NULL DEFAULT 209715200,
  `ignored_extensions` json NOT NULL,
  `scan_interval_seconds` int NOT NULL DEFAULT 300,
  `delete_propagation` tinyint(1) NOT NULL DEFAULT '1',
  `is_active` tinyint(1) NOT NULL DEFAULT '1',
  `is_running` tinyint(1) NOT NULL DEFAULT '0',
  `lock_acquired_at` timestamp NULL DEFAULT NULL,
  `last_sync_at` timestamp NULL DEFAULT NULL,
  `last_sync_status` varchar(32) DEFAULT NULL,
  `created_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_sp_int_dataset` (`dataset_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `ai_hub_sharepoint_integration_drives` (
  `integration_id` int NOT NULL,
  `drive_id` varchar(255) NOT NULL,
  `drive_name` varchar(255) NOT NULL,
  `delta_link` text,
  `last_sync_at` timestamp NULL DEFAULT NULL,
  `discovered_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`integration_id`,`drive_id`),
  KEY `idx_sp_drives_integration` (`integration_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `ai_hub_integration_sync_runs` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `integration_id` int NOT NULL,
  `integration_type` varchar(32) NOT NULL,
  `started_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `finished_at` timestamp NULL DEFAULT NULL,
  `status` varchar(32) NOT NULL,
  `added` int NOT NULL DEFAULT 0,
  `updated` int NOT NULL DEFAULT 0,
  `deleted` int NOT NULL DEFAULT 0,
  `failed` int NOT NULL DEFAULT 0,
  PRIMARY KEY (`id`),
  KEY `idx_int_runs_type_started` (`integration_type`,`started_at`),
  KEY `idx_int_runs_integration` (`integration_id`,`integration_type`,`started_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `ai_hub_integration_sync_events` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `run_id` bigint NOT NULL,
  `integration_id` int NOT NULL,
  `integration_type` varchar(32) NOT NULL,
  `level` varchar(16) NOT NULL,
  `message` text NOT NULL,
  `file_path` varchar(1024) DEFAULT NULL,
  `drive_id` varchar(255) DEFAULT NULL,
  `drive_name` varchar(255) DEFAULT NULL,
  `created_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_int_events_run` (`run_id`,`id`),
  KEY `idx_int_events_level` (`integration_type`,`level`,`created_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `ai_hub_integration_file_mappings` (
  `integration_id` int NOT NULL,
  `integration_type` varchar(32) NOT NULL,
  `drive_id` varchar(255) NOT NULL,
  `external_item_id` varchar(255) NOT NULL,
  `external_etag` varchar(255) DEFAULT NULL,
  `ragflow_document_id` varchar(64) NOT NULL,
  `last_status` varchar(32) NOT NULL,
  `last_error` text,
  `updated_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`integration_id`,`drive_id`,`external_item_id`),
  KEY `idx_int_map_ragflow_doc` (`ragflow_document_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
