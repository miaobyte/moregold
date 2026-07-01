// MySQL 连接池 + 查询工具
import mysql from "mysql2/promise";

const pool = mysql.createPool({
  host: "bj-cdb-9ermqj8g.sql.tencentcdb.com",
  port: 26092,
  user: "gold_ro",
  password: "BNbQMsn4hhnmuw6P",
  database: "gold",
  charset: "utf8mb4",
  connectionLimit: 3,
});

export function query(sql, params = []) {
  return pool.execute(sql, params).then(([rows]) => rows);
}
