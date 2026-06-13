# create_users.py —— 批量建账号的小脚本
#
# 用法：
#   1. 在下面 MEMBERS 列表里填好师兄师姐名单（用户名、姓名、初始密码）
#   2. 运行一次：  python create_users.py
#   3. 把每个人的“用户名 + 初始密码”发给本人，他们登录后自己改密码
#
# 重复运行不会重复创建：已存在的用户名会自动跳过。

from app import app, db, User

# ★★★ 在这里填名单 ★★★
# 格式： ("登录用户名", "显示姓名", 入学年份, "初始密码", 是否管理员)
# 用户名建议用拼音或学号，简单好记；初始密码可以统一一个，让大家进去自己改。
# 入学年份是必填的；其余信息（单位、籍贯、微信等）让本人登录后自己补。
# 最后一项 True 表示管理员（能删任意相册照片）——把你自己设成 True 即可，其他人留 False。
MEMBERS = [
    ("zhangsan", "张三", 2022, "123456", True),   # ← 这位是管理员
    ("lisi",     "李四", 2023, "123456", False),
    ("wangwu",   "王五", 2023, "123456", False),
    # …继续往下加，一行一个人
]


def main():
    with app.app_context():
        created, skipped = 0, 0
        for username, name, enroll_year, password, is_admin in MEMBERS:
            # 已存在就跳过，避免重复
            if User.query.filter_by(username=username).first():
                print(f"跳过（已存在）：{username}")
                skipped += 1
                continue

            user = User(username=username, name=name,
                        enroll_year=enroll_year, is_admin=is_admin)
            user.set_password(password)        # 自动加密存储
            db.session.add(user)
            created += 1
            print(f"已创建：{username}（{name}）{'[管理员]' if is_admin else ''}")

        db.session.commit()
        print(f"\n完成：新建 {created} 个，跳过 {skipped} 个。")


if __name__ == "__main__":
    main()
