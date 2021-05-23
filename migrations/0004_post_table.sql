-- DROP TABLE IF EXISTS `post`;
CREATE TABLE IF NOT EXISTS `post` (
  `id` bigint(20) NOT NULL AUTO_INCREMENT PRIMARY KEY,
  `author_id` bigint(20) NOT NULL,
  `text` text NOT NULL,
  `created_at` timestamp NOT NULL,
  `updated_at` timestamp NULL ON UPDATE CURRENT_TIMESTAMP,
  FOREIGN KEY (`author_id`) REFERENCES `user` (`id`) ON DELETE CASCADE
) ENGINE='InnoDB'  DEFAULT CHARSET=utf8 COLLATE=utf8_bin;
