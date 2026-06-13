# reset_db.py —— 重建数据库
#
# 什么时候用：当我们给数据库“加了新字段/新表”，旧库结构对不上、报
#   “no such column …” 这类错时，跑一次这个脚本即可。
#
# ⚠️ 注意：它会清空所有账号和相册记录，然后按 create_users.py 的名单重建账号。
#   现阶段（还没上线、只有测试数据）随便用。等真正上线、有真实数据后，
#   就不要再跑它了（那时候改结构要用“数据库迁移”，到时我再教你）。
#
# 用法：先确保没有 python app.py 在运行（占用文件），然后：
#   python reset_db.py

from app import app, db
import create_users

with app.app_context():
    db.drop_all()      # 删掉所有表
    db.create_all()    # 按最新结构重建
    print("数据库结构已重建。")

# 重新建账号（复用 create_users.py 里的名单）
create_users.main()
