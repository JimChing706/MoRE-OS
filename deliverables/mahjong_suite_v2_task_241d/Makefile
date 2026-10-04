# Tetris 项目 — GNU Make 命令速查
#
# 常用命令：
#   make        - 构建 release + 跑单元测试
#   make build  - 仅 cargo build --release
#   make test   - 单元测试（release）
#   make cover  - 覆盖率（需 cargo-tarpaulin）
#   make serve  - 启动前端静态服务器 :8080
#   make clean  - 清理 target

.PHONY: all build test cover serve clean

all: build test

build:
	cargo build --release

test:
	cargo test --release -q

cover:
	cargo tarpaulin --out Html --output-dir ./coverage || (echo "提示: cargo install cargo-tarpaulin" && exit 1)

serve:
	python3 -m http.server 8080 --directory frontend

clean:
	cargo clean
