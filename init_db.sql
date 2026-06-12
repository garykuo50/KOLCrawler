-- KOL Crawler Database Initialization
-- Run: mysql -h 192.168.11.217 -u root -p < init_db.sql

CREATE DATABASE IF NOT EXISTS kol_db
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;

USE kol_db;

CREATE TABLE IF NOT EXISTS kol_records (
    id            INT AUTO_INCREMENT PRIMARY KEY,
    keyword       VARCHAR(255)  NOT NULL COMMENT '搜尋關鍵字',
    channel_name  VARCHAR(500)  NOT NULL COMMENT '頻道名稱',
    channel_url   VARCHAR(1000) NOT NULL COMMENT '頻道網址',
    subscribers   VARCHAR(50)   DEFAULT NULL COMMENT '訂閱數 (原始字串, e.g. 1.2M)',
    avg_views     VARCHAR(50)   DEFAULT NULL COMMENT '平均觀看人次 (最近 ~30 支)',
    max_views     VARCHAR(50)   DEFAULT NULL COMMENT '最高觀看人次 (熱門影片)',
    recorded_at   DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '紀錄時間',
    INDEX idx_keyword     (keyword),
    INDEX idx_recorded_at (recorded_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
