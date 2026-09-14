# -*- coding: utf-8 -*-
"""学习中心增强数据：
- 关键字详解（每种语言每个关键字都有介绍/语法/示例）
- 标准库模块用法（每种语言至少 5 个模块完整用法）
- 知识点详情生成（语文/数学/英语每个知识点可点击查看完整内容）
"""
import re

# ============================================================
# 一、关键字详解：通用库 + 各语言特有补充
# 格式：{word: {"desc": "...", "syntax": "...", "example": "..."}}
# ============================================================

# 通用编程关键字（大多数语言共有，作为回退）
_COMMON_KEYWORDS = {
    "if": {"desc": "条件判断语句，当条件为真时执行对应代码块。", "syntax": "if (condition) { ... }", "example": "if (x > 0) { print('positive'); }"},
    "else": {"desc": "与 if 配对，条件为假时执行的分支。", "syntax": "if (cond) { ... } else { ... }", "example": "if (x > 0) { ... } else { ... }"},
    "elif": {"desc": "Python 中的 else if，多分支条件判断。", "syntax": "if cond1: ... elif cond2: ...", "example": "if x > 0: print('+')\nelif x < 0: print('-')"},
    "else if": {"desc": "多分支条件判断，在 if 和 else 之间增加条件。", "syntax": "if (c1) {...} else if (c2) {...}", "example": "if (x>0){...} else if (x<0){...}"},
    "for": {"desc": "循环语句，用于遍历序列或按次数重复执行。", "syntax": "for (init; cond; update) { ... }", "example": "for (int i=0; i<10; i++) { ... }"},
    "while": {"desc": "当型循环，条件为真时重复执行代码块。", "syntax": "while (condition) { ... }", "example": "while (n > 0) { n--; }"},
    "do": {"desc": "do-while 循环，先执行一次再判断条件。", "syntax": "do { ... } while (cond);", "example": "do { x++; } while (x < 10);"},
    "break": {"desc": "立即跳出当前循环或 switch 语句。", "syntax": "break;", "example": "for (...) { if (done) break; }"},
    "continue": {"desc": "跳过本次循环剩余语句，进入下一次迭代。", "syntax": "continue;", "example": "for (...) { if (skip) continue; ... }"},
    "return": {"desc": "从函数返回值并结束函数执行。", "syntax": "return value;", "example": "int add(a,b) { return a+b; }"},
    "class": {"desc": "定义类，面向对象编程的基本结构。", "syntax": "class Name { ... }", "example": "class Person { String name; }"},
    "def": {"desc": "Python 中定义函数的关键字。", "syntax": "def name(args): ...", "example": "def greet(name): print('Hi '+name)"},
    "function": {"desc": "JavaScript 中定义函数的关键字。", "syntax": "function name(args) { ... }", "example": "function add(a,b){return a+b;}"},
    "import": {"desc": "导入外部模块或包中的功能。", "syntax": "import module;", "example": "import os; print(os.getcwd())"},
    "from": {"desc": "Python 中从模块导入指定对象。", "syntax": "from module import name", "example": "from math import sqrt"},
    "as": {"desc": "为导入的模块或对象起别名。", "syntax": "import module as alias", "example": "import numpy as np"},
    "in": {"desc": "成员运算符，判断元素是否在序列中；也用于 for 循环遍历。", "syntax": "x in collection", "example": "if 'a' in 'abc': print('yes')"},
    "is": {"desc": "身份运算符，判断两个对象是否为同一个对象。", "syntax": "a is b", "example": "if a is None: print('empty')"},
    "not": {"desc": "逻辑非运算符，对布尔值取反。", "syntax": "not condition", "example": "if not ready: wait()"},
    "and": {"desc": "逻辑与运算符，两边都为真结果才为真。", "syntax": "a and b", "example": "if age > 0 and age < 120: ..."},
    "or": {"desc": "逻辑或运算符，任一为真结果即为真。", "syntax": "a or b", "example": "if x < 0 or x > 100: ..."},
    "True": {"desc": "Python 布尔真值。", "syntax": "True", "example": "flag = True"},
    "False": {"desc": "Python 布尔假值。", "syntax": "False", "example": "flag = False"},
    "None": {"desc": "Python 空值对象，表示不存在或无值。", "syntax": "None", "example": "result = None"},
    "null": {"desc": "空引用，表示对象不存在（JS/Java/C#等）。", "syntax": "null", "example": "String s = null;"},
    "void": {"desc": "表示函数无返回值，或空类型。", "syntax": "void func() { ... }", "example": "void print() { ... }"},
    "int": {"desc": "整数类型声明。", "syntax": "int x = 10;", "example": "int count = 0;"},
    "float": {"desc": "单精度浮点数类型。", "syntax": "float x = 3.14;", "example": "float pi = 3.14f;"},
    "double": {"desc": "双精度浮点数类型。", "syntax": "double x = 3.14;", "example": "double pi = 3.14159;"},
    "char": {"desc": "字符类型，存储单个字符。", "syntax": "char c = 'A';", "example": "char grade = 'A';"},
    "string": {"desc": "字符串类型。", "syntax": "string s = \"hello\";", "example": "string name = \"Tom\";"},
    "bool": {"desc": "布尔类型，值为 true 或 false。", "syntax": "bool flag = true;", "example": "bool ok = true;"},
    "boolean": {"desc": "Java 中的布尔类型。", "syntax": "boolean flag = true;", "example": "boolean ready = false;"},
    "public": {"desc": "访问修饰符，表示公开可访问。", "syntax": "public class/method/field", "example": "public void run() { ... }"},
    "private": {"desc": "访问修饰符，表示仅类内部可访问。", "syntax": "private field/method", "example": "private int age;"},
    "protected": {"desc": "访问修饰符，表示子类和同包可访问。", "syntax": "protected field/method", "example": "protected void init() { ... }"},
    "static": {"desc": "静态修饰符，属于类而非实例。", "syntax": "static field/method", "example": "static int count = 0;"},
    "final": {"desc": "表示不可变（变量）、不可继承（类）、不可重写（方法）。", "syntax": "final type name = value;", "example": "final double PI = 3.14;"},
    "const": {"desc": "常量声明，值不可修改。", "syntax": "const type NAME = value;", "example": "const int MAX = 100;"},
    "var": {"desc": "类型推断变量声明（JS/C#等）。", "syntax": "var x = value;", "example": "var list = new Array();"},
    "let": {"desc": "JS 块级作用域变量声明。", "syntax": "let x = 10;", "example": "let count = 0;"},
    "new": {"desc": "创建对象实例或分配内存。", "syntax": "new ClassName()", "example": "Person p = new Person();"},
    "this": {"desc": "引用当前对象实例。", "syntax": "this.field / this.method()", "example": "this.name = name;"},
    "super": {"desc": "引用父类对象或构造方法。", "syntax": "super.method() / super(args)", "example": "super(name);"},
    "extends": {"desc": "类继承父类。", "syntax": "class Child extends Parent", "example": "class Dog extends Animal { ... }"},
    "implements": {"desc": "类实现接口。", "syntax": "class C implements I", "example": "class Runner implements Runnable { ... }"},
    "interface": {"desc": "定义接口，规定方法契约。", "syntax": "interface Name { ... }", "example": "interface Drawable { void draw(); }"},
    "abstract": {"desc": "抽象类或抽象方法，不能直接实例化。", "syntax": "abstract class/method", "example": "abstract class Shape { ... }"},
    "try": {"desc": "异常处理开始，包裹可能抛出异常的代码。", "syntax": "try { ... } catch(e) { ... }", "example": "try { risky(); } catch(e) { log(e); }"},
    "catch": {"desc": "捕获并处理异常。", "syntax": "catch (ExceptionType e) { ... }", "example": "catch (IOException e) { ... }"},
    "finally": {"desc": "无论是否异常都会执行的清理代码。", "syntax": "finally { ... }", "example": "finally { file.close(); }"},
    "throw": {"desc": "主动抛出异常。", "syntax": "throw new Exception();", "example": "throw new Error('invalid');"},
    "throws": {"desc": "Java 方法声明可能抛出的异常。", "syntax": "void m() throws Exception", "example": "void read() throws IOException { ... }"},
    "switch": {"desc": "多分支选择语句，根据值匹配 case。", "syntax": "switch (expr) { case v: ... }", "example": "switch (n) { case 1: ... break; }"},
    "case": {"desc": "switch 中的分支标签。", "syntax": "case value: ...", "example": "case 'A': grade(); break;"},
    "default": {"desc": "switch 中无匹配时的默认分支；也可作默认参数/方法。", "syntax": "default: ...", "example": "default: println('other');"},
    "struct": {"desc": "C/C++/Go/Rust 中定义结构体。", "syntax": "struct Name { ... }", "example": "struct Point { int x; int y; };"},
    "enum": {"desc": "定义枚举类型，一组命名常量。", "syntax": "enum Name { A, B, C }", "example": "enum Color { RED, GREEN, BLUE }"},
    "typedef": {"desc": "C/C++ 中为类型起别名。", "syntax": "typedef old new;", "example": "typedef int Integer;"},
    "union": {"desc": "C/C++ 联合体，所有成员共享内存。", "syntax": "union Name { ... }", "example": "union Data { int i; float f; };"},
    "sizeof": {"desc": "C/C++ 中获取类型或变量的字节大小。", "syntax": "sizeof(type/var)", "example": "int s = sizeof(int);"},
    "namespace": {"desc": "C++/C# 中定义命名空间，避免命名冲突。", "syntax": "namespace Name { ... }", "example": "namespace std { ... }"},
    "template": {"desc": "C++ 模板，实现泛型编程。", "syntax": "template <typename T>", "example": "template <typename T> T max(T a,T b)"},
    "typename": {"desc": "C++ 模板中声明类型参数。", "syntax": "template <typename T>", "example": "template <typename T> class Vec { ... }"},
    "operator": {"desc": "C++ 中重载运算符。", "syntax": "operator op(...)", "example": "bool operator==(const T& o)"},
    "virtual": {"desc": "C++ 虚函数，支持运行时多态。", "syntax": "virtual ret name(args)", "example": "virtual void draw();"},
    "override": {"desc": "C++/C# 中显式标记重写父类方法。", "syntax": "ret name(args) override", "example": "void draw() override { ... }"},
    "public": {"desc": "公开访问修饰符。", "syntax": "public:", "example": "public: void run();"},
    "delete": {"desc": "C++ 释放 new 分配的内存；JS 删除对象属性。", "syntax": "delete ptr;", "example": "delete[] arr;"},
    "malloc": {"desc": "C 语言动态分配内存（函数，非关键字但常用）。", "syntax": "malloc(size)", "example": "int* p = malloc(sizeof(int)*10);"},
    "free": {"desc": "C 语言释放 malloc 分配的内存。", "syntax": "free(ptr)", "example": "free(p);"},
    "include": {"desc": "C/C++ 预处理器包含头文件。", "syntax": "#include <header>", "example": "#include <stdio.h>"},
    "define": {"desc": "C/C++ 预处理器定义宏。", "syntax": "#define NAME value", "example": "#define MAX 100"},
    "package": {"desc": "Java/Kotlin 声明包名。", "syntax": "package com.example;", "example": "package com.app;"},
    "synchronized": {"desc": "Java 线程同步，保证原子性和可见性。", "syntax": "synchronized(obj) { ... }", "example": "synchronized void inc() { n++; }"},
    "volatile": {"desc": "变量可见性修饰，禁止指令重排。", "syntax": "volatile type name;", "example": "volatile boolean running = true;"},
    "transient": {"desc": "Java 中标记字段不参与序列化。", "syntax": "transient type name;", "example": "transient String cache;"},
    "instanceof": {"desc": "Java/JS 中判断对象是否为某类型实例。", "syntax": "obj instanceof Type", "example": "if (obj instanceof String) { ... }"},
    "assert": {"desc": "断言，调试时验证条件是否成立。", "syntax": "assert condition;", "example": "assert x > 0 : 'x must be positive';"},
    "strictfp": {"desc": "Java 中强制使用严格浮点计算。", "syntax": "strictfp class/method", "example": "strictfp double calc() { ... }"},
    "native": {"desc": "Java 中标记方法由本地代码实现。", "syntax": "native ret name(args);", "example": "native void start();"},
    "goto": {"desc": "无条件跳转（多数语言不推荐使用）。", "syntax": "goto label;", "example": "goto cleanup;"},
    "const": {"desc": "常量，不可修改。", "syntax": "const type NAME = val;", "example": "const double PI = 3.14159;"},
    "export": {"desc": "JS/TS 中导出模块成员。", "syntax": "export const/function/class", "example": "export function add(a,b){return a+b;}"},
    "async": {"desc": "声明异步函数，返回 Promise。", "syntax": "async function name() { ... }", "example": "async function fetchData() { ... }"},
    "await": {"desc": "等待 Promise 完成，仅在 async 函数内使用。", "syntax": "await promise", "example": "const data = await fetch(url);"},
    "yield": {"desc": "生成器函数中暂停并返回值。", "syntax": "yield value;", "example": "yield i * 2;"},
    "typeof": {"desc": "JS 中获取值的类型字符串。", "syntax": "typeof value", "example": "typeof 42 === 'number'"},
    "instanceof": {"desc": "判断对象是否为构造函数的实例。", "syntax": "obj instanceof Constructor", "example": "[] instanceof Array"},
    "delete": {"desc": "JS 删除对象属性或数组元素。", "syntax": "delete obj.prop", "example": "delete user.name;"},
    "with": {"desc": "JS 中扩展作用域链（不推荐）。", "syntax": "with (obj) { ... }", "example": "with (Math) { x = cos(PI); }"},
    "func": {"desc": "Go 中定义函数。", "syntax": "func name(args) ret { ... }", "example": "func add(a, b int) int { return a+b }"},
    "package": {"desc": "Go 中声明所属包。", "syntax": "package main", "example": "package main"},
    "go": {"desc": "Go 中启动一个 goroutine 并发执行。", "syntax": "go func() { ... }()", "example": "go handle(conn)"},
    "chan": {"desc": "Go 中声明通道类型，用于 goroutine 通信。", "syntax": "chan type", "example": "ch := make(chan int)"},
    "select": {"desc": "Go 中多路等待通道操作。", "syntax": "select { case <-ch: ... }", "example": "select { case v := <-ch: ... }"},
    "range": {"desc": "Go 中遍历数组/切片/映射/通道；Python 中生成整数序列。", "syntax": "for k, v := range collection", "example": "for i, v := range arr { ... }"},
    "map": {"desc": "Go 中映射类型；JS 中数组映射方法。", "syntax": "map[K]V", "example": "m := make(map[string]int)"},
    "slice": {"desc": "Go 切片类型（常用类型）。", "syntax": "[]type", "example": "var s []int = []int{1,2,3}"},
    "interface": {"desc": "Go 中定义接口类型。", "syntax": "interface { ... }", "example": "type Reader interface { Read() }"},
    "defer": {"desc": "Go 中延迟执行函数调用，常用于资源清理。", "syntax": "defer func()", "example": "defer file.Close()"},
    "goroutine": {"desc": "Go 轻量级线程（概念，非关键字）。", "syntax": "go f()", "example": "go worker()"},
    "struct": {"desc": "Go 中定义结构体。", "syntax": "type Name struct { ... }", "example": "type Point struct { X, Y int }"},
    "type": {"desc": "Go 中定义类型别名或新类型。", "syntax": "type Name underlying", "example": "type ID string"},
    "fn": {"desc": "Rust 中定义函数。", "syntax": "fn name(args) -> ret { ... }", "example": "fn add(a: i32, b: i32) -> i32 { a+b }"},
    "let": {"desc": "Rust 中声明变量（默认不可变）。", "syntax": "let name = value;", "example": "let x = 5;"},
    "mut": {"desc": "Rust 中标记变量可变。", "syntax": "let mut name = value;", "example": "let mut count = 0;"},
    "pub": {"desc": "Rust 中标记项为公开可见。", "syntax": "pub fn/struct/mod", "example": "pub fn run() { ... }"},
    "impl": {"desc": "Rust 中为类型实现方法或 trait。", "syntax": "impl Type { ... }", "example": "impl Point { fn dist(&self) -> f64 }"},
    "trait": {"desc": "Rust 中定义 trait（类似接口）。", "syntax": "trait Name { ... }", "example": "trait Draw { fn draw(&self); }"},
    "mod": {"desc": "Rust 中定义模块。", "syntax": "mod name { ... }", "example": "mod utils { ... }"},
    "crate": {"desc": "Rust 中引用当前 crate 根。", "syntax": "crate::path", "example": "use crate::utils::helper;"},
    "use": {"desc": "Rust/其他语言中导入名称到作用域。", "syntax": "use path::to::Item;", "example": "use std::collections::HashMap;"},
    "match": {"desc": "Rust/Swift 中模式匹配。", "syntax": "match expr { ... }", "example": "match x { 0 => 'zero', _ => 'other' }"},
    "loop": {"desc": "Rust 中无限循环。", "syntax": "loop { ... }", "example": "loop { if done { break; } }"},
    "move": {"desc": "Rust 闭包中捕获变量所有权。", "syntax": "move |args| { ... }", "example": "let c = move || x + 1;"},
    "where": {"desc": "Rust 中添加 trait 约束子句。", "syntax": "where T: Trait", "example": "fn f<T>(x: T) where T: Clone"},
    "self": {"desc": "Rust/Python 中引用当前实例。", "syntax": "self.method() / self.field", "example": "fn area(&self) -> f64"},
    "Self": {"desc": "Rust 中表示实现的类型本身。", "syntax": "Self", "example": "fn new() -> Self { ... }"},
    "dyn": {"desc": "Rust 中动态分发 trait 对象。", "syntax": "dyn Trait", "example": "Box<dyn Draw>"},
    "async": {"desc": "Rust/JS 中异步函数。", "syntax": "async fn name() { ... }", "example": "async fn fetch() { ... }"},
    "await": {"desc": "Rust/JS 中等待 Future。", "syntax": "expr.await", "example": "let r = fetch().await;"},
    "enum": {"desc": "Rust 中定义枚举（可带数据）。", "syntax": "enum Name { A, B(i32) }", "example": "enum Option<T> { Some(T), None }"},
    "Result": {"desc": "Rust 标准结果类型（常用类型）。", "syntax": "Result<T, E>", "example": "fn parse() -> Result<i32, Err>"},
    "Option": {"desc": "Rust 可选值类型（常用类型）。", "syntax": "Option<T>", "example": "fn find() -> Option<i32>"},
    "Some": {"desc": "Rust Option 的有值变体。", "syntax": "Some(value)", "example": "Some(42)"},
    "None": {"desc": "Rust Option 的空值变体。", "syntax": "None", "example": "None"},
    "Ok": {"desc": "Rust Result 的成功变体。", "syntax": "Ok(value)", "example": "Ok(42)"},
    "Err": {"desc": "Rust Result 的错误变体。", "syntax": "Err(error)", "example": "Err('fail')"},
    "protocol": {"desc": "Swift 中定义协议（类似接口）。", "syntax": "protocol Name { ... }", "example": "protocol Drawable { func draw() }"},
    "extension": {"desc": "Swift 中为已有类型添加功能。", "syntax": "extension Type { ... }", "example": "extension Int { var sq: Int { self*self } }"},
    "guard": {"desc": "Swift 中提前退出条件判断。", "syntax": "guard cond else { ... }", "example": "guard let x = opt else { return }"},
    "if let": {"desc": "Swift 中可选绑定。", "syntax": "if let x = opt { ... }", "example": "if let name = optionalName { ... }"},
    "optional": {"desc": "Swift 可选类型概念（用 ? 标记）。", "syntax": "Type?", "example": "var name: String?"},
    "struct": {"desc": "Swift 中定义值类型结构体。", "syntax": "struct Name { ... }", "example": "struct Point { var x, y: Double }"},
    "func": {"desc": "Swift 中定义函数。", "syntax": "func name(args) -> ret { ... }", "example": "func add(a: Int, b: Int) -> Int { a+b }"},
    "var": {"desc": "Swift 中声明可变变量。", "syntax": "var name = value", "example": "var count = 0"},
    "let": {"desc": "Swift 中声明不可变常量。", "syntax": "let name = value", "example": "let pi = 3.14"},
    "init": {"desc": "Swift 中初始化方法。", "syntax": "init(args) { ... }", "example": "init(name: String) { ... }"},
    "deinit": {"desc": "Swift 中反初始化方法。", "syntax": "deinit { ... }", "example": "deinit { cleanup() }"},
    "subscript": {"desc": "Swift 中定义下标访问。", "syntax": "subscript(idx: Int) -> T { ... }", "example": "subscript(i: Int) -> Element"},
    "associatedtype": {"desc": "Swift 协议中关联类型。", "syntax": "associatedtype Name", "example": "associatedtype Element"},
    "typealias": {"desc": "Swift 中为类型起别名。", "syntax": "typealias New = Old", "example": "typealias JSON = [String: Any]"},
    "inout": {"desc": "Swift 中标记参数可在函数内修改。", "syntax": "inout type", "example": "func swap(_ a: inout Int, _ b: inout Int)"},
    "throws": {"desc": "Swift 中标记函数可抛出错误。", "syntax": "func name() throws -> ret", "example": "func load() throws -> Data"},
    "rethrows": {"desc": "Swift 中标记函数仅当参数函数抛错时才抛错。", "syntax": "func name(_ f: () throws -> ()) rethrows", "example": "func map(_ f: (T) throws -> U) rethrows -> [U]"},
    "try": {"desc": "Swift 中调用可抛错函数。", "syntax": "try expr / try? / try!", "example": "let data = try load()"},
    "catch": {"desc": "Swift 中捕获错误。", "syntax": "catch { ... }", "example": "do { try f() } catch { log() }"},
    "defer": {"desc": "Swift 中延迟执行到作用域结束。", "syntax": "defer { ... }", "example": "defer { file.close() }"},
    "operator": {"desc": "Swift 中自定义/重载运算符。", "syntax": "operator func", "example": "func + (l: Point, r: Point) -> Point"},
    "infix": {"desc": "Swift 中声明中缀运算符。", "syntax": "infix operator Name", "example": "infix operator ++"},
    "prefix": {"desc": "Swift 中声明前缀运算符。", "syntax": "prefix operator Name", "example": "prefix operator ++"},
    "postfix": {"desc": "Swift 中声明后缀运算符。", "syntax": "postfix operator Name", "example": "postfix operator ++"},
    "convenience": {"desc": "Swift 中标记便利初始化方法。", "syntax": "convenience init(args)", "example": "convenience init() { self.init(x: 0) }"},
    "required": {"desc": "Swift 中要求子类必须实现的初始化方法。", "syntax": "required init(args)", "example": "required init?(coder: NSCoder)"},
    "lazy": {"desc": "Swift 中延迟存储属性，首次访问才计算。", "syntax": "lazy var name = expr", "example": "lazy var formatter = DateFormatter()"},
    "didSet": {"desc": "Swift 属性观察器，值设置后调用。", "syntax": "didSet { ... }", "example": "var x = 0 { didSet { print(x) } }"},
    "willSet": {"desc": "Swift 属性观察器，值设置前调用。", "syntax": "willSet { ... }", "example": "var x = 0 { willSet { print(newValue) } }"},
    "data class": {"desc": "Kotlin 中数据类，自动生成 equals/hashCode/toString。", "syntax": "data class Name(val p: T)", "example": "data class User(val name: String)"},
    "sealed class": {"desc": "Kotlin 密封类，限制继承。", "syntax": "sealed class Name", "example": "sealed class Result"},
    "object": {"desc": "Kotlin 中声明单例对象。", "syntax": "object Name { ... }", "example": "object Config { ... }"},
    "companion": {"desc": "Kotlin 伴生对象，类似静态成员。", "syntax": "companion object { ... }", "example": "companion object { const val TAG = 'X' }"},
    "val": {"desc": "Kotlin 中声明只读变量。", "syntax": "val name = value", "example": "val pi = 3.14"},
    "var": {"desc": "Kotlin 中声明可变变量。", "syntax": "var name = value", "example": "var count = 0"},
    "fun": {"desc": "Kotlin 中定义函数。", "syntax": "fun name(args): ret { ... }", "example": "fun add(a: Int, b: Int) = a + b"},
    "when": {"desc": "Kotlin 中分支表达式（类似 switch 增强）。", "syntax": "when (x) { 1 -> ... }", "example": "when (x) { 1 -> 'one' else -> 'other' }"},
    "init": {"desc": "Kotlin 初始化块。", "syntax": "init { ... }", "example": "init { require(age > 0) }"},
    "constructor": {"desc": "Kotlin 中声明构造函数。", "syntax": "constructor(args)", "example": "constructor(name: String): this()"},
    "open": {"desc": "Kotlin 中标记类可被继承或方法可被重写。", "syntax": "open class/method", "example": "open class Base { open fun f() }"},
    "override": {"desc": "Kotlin 中标记重写父类成员。", "syntax": "override fun/val", "example": "override fun f() { ... }"},
    "lateinit": {"desc": "Kotlin 中延迟初始化非空属性。", "syntax": "lateinit var name: Type", "example": "lateinit var api: ApiService"},
    "by": {"desc": "Kotlin 中委托关键字。", "syntax": "val/var by delegate", "example": "val p by lazy { ... }"},
    "suspend": {"desc": "Kotlin 协程中挂起函数。", "syntax": "suspend fun name() { ... }", "example": "suspend fun load(): Data"},
    "inline": {"desc": "Kotlin 中内联函数，消除 lambda 开销。", "syntax": "inline fun name()", "example": "inline fun measure(block: () -> Unit)"},
    "reified": {"desc": "Kotlin 中具体化类型参数（需 inline）。", "syntax": "reified T", "example": "inline fun <reified T> check()"},
    "tailrec": {"desc": "Kotlin 中标记尾递归函数，编译器优化为循环。", "syntax": "tailrec fun name()", "example": "tailrec fun fact(n: Int, acc: Int): Int"},
    "infix": {"desc": "Kotlin 中标记中缀函数。", "syntax": "infix fun name()", "example": "infix fun Int.and(other: Int)"},
    "operator": {"desc": "Kotlin 中重载运算符。", "syntax": "operator fun name()", "example": "operator fun plus(other: Point)"},
    "enum": {"desc": "Kotlin 中定义枚举类。", "syntax": "enum class Name { ... }", "example": "enum class Color { RED, GREEN }"},
    "annotation": {"desc": "Kotlin 中定义注解类。", "syntax": "annotation class Name", "example": "annotation class Inject"},
    "internal": {"desc": "Kotlin 中模块内可见修饰符。", "syntax": "internal fun/val", "example": "internal val cache = ..."},
    "out": {"desc": "Kotlin 协变类型参数。", "syntax": "class C<out T>", "example": "interface Producer<out T>"},
    "in": {"desc": "Kotlin 逆变类型参数；也用于 in 表达式。", "syntax": "class C<in T>", "example": "interface Consumer<in T>"},
    "field": {"desc": "Kotlin 中属性的幕后字段。", "syntax": "field", "example": "set(value) { field = value }"},
    "get": {"desc": "Kotlin 属性 getter。", "syntax": "get() = ...", "example": "val size get() = list.size"},
    "set": {"desc": "Kotlin 属性 setter。", "syntax": "set(value) { ... }", "example": "var x = 0 set(v) { field = v }"},
    "using": {"desc": "C# 中确保资源释放的语句。", "syntax": "using (var r = ...) { ... }", "example": "using (var fs = new FileStream()) { ... }"},
    "namespace": {"desc": "C# 中声明命名空间。", "syntax": "namespace Name { ... }", "example": "namespace MyApp.Models"},
    "partial": {"desc": "C# 中分部类/方法，可在多个文件中定义。", "syntax": "partial class Name", "example": "partial class Form1 { ... }"},
    "delegate": {"desc": "C# 中定义委托类型（方法引用）。", "syntax": "delegate ret Name(args)", "example": "delegate int Handler(int x)"},
    "event": {"desc": "C# 中声明事件。", "syntax": "event Handler Name;", "example": "public event EventHandler Click;"},
    "async": {"desc": "C# 异步方法。", "syntax": "async Task name() { ... }", "example": "async Task<string> ReadAsync()"},
    "await": {"desc": "C# 中等待异步任务。", "syntax": "await task", "example": "var data = await ReadAsync();"},
    "get": {"desc": "C# 属性 getter。", "syntax": "get { ... }", "example": "public int X { get; set; }"},
    "set": {"desc": "C# 属性 setter。", "syntax": "set { ... }", "example": "public int X { get; set; }"},
    "value": {"desc": "C# setter 中的隐式参数。", "syntax": "value", "example": "set { _x = value; }"},
    "base": {"desc": "C# 中引用父类。", "syntax": "base.method() / base(args)", "example": "base(name);"},
    "this": {"desc": "C# 中引用当前实例；也可作扩展方法第一个参数。", "syntax": "this.field", "example": "this.Name = name;"},
    "lock": {"desc": "C# 中线程同步锁。", "syntax": "lock (obj) { ... }", "example": "lock (_sync) { count++; }"},
    "unsafe": {"desc": "C# 中允许指针操作的上下文。", "syntax": "unsafe { ... }", "example": "unsafe { int* p = &x; }"},
    "fixed": {"desc": "C# 中固定托管内存指针。", "syntax": "fixed (type* p = &arr[0]) { ... }", "example": "fixed (int* p = arr) { ... }"},
    "stackalloc": {"desc": "C# 中在栈上分配内存。", "syntax": "stackalloc type[n]", "example": "int* buf = stackalloc int[256];"},
    "readonly": {"desc": "C# 中只读字段，仅构造函数可赋值。", "syntax": "readonly type name;", "example": "readonly int id;"},
    "sealed": {"desc": "C# 中标记类不可被继承。", "syntax": "sealed class Name", "example": "sealed class Util { ... }"},
    "virtual": {"desc": "C# 中虚方法，可被子类重写。", "syntax": "virtual ret name(args)", "example": "public virtual void Draw() { ... }"},
    "abstract": {"desc": "C# 抽象类/方法，不能实例化。", "syntax": "abstract class/method", "example": "public abstract double Area();"},
    "extern": {"desc": "C# 中标记外部方法（DllImport）。", "syntax": "extern ret name(args);", "example": "extern static int MessageBox(...);"},
    "params": {"desc": "C# 可变参数数组。", "syntax": "params type[] name", "example": "int Sum(params int[] nums)"},
    "ref": {"desc": "C# 引用参数，方法内修改影响外部。", "syntax": "ref type name", "example": "void Swap(ref int a, ref int b)"},
    "out": {"desc": "C# 输出参数，方法必须赋值。", "syntax": "out type name", "example": "bool TryParse(string s, out int n)"},
    "in": {"desc": "C# 只读引用参数。", "syntax": "in type name", "example": "void Calc(in Point p)"},
    "is": {"desc": "C# 类型检查与模式匹配。", "syntax": "expr is Type", "example": "if (obj is string s) { ... }"},
    "as": {"desc": "C# 安全类型转换，失败返回 null。", "syntax": "expr as Type", "example": "var s = obj as string;"},
    "nameof": {"desc": "C# 获取变量/类型/成员的名称字符串。", "syntax": "nameof(expr)", "example": "nameof(Person.Name)"},
    "sizeof": {"desc": "C# 获取非托管类型大小。", "syntax": "sizeof(type)", "example": "int s = sizeof(int);"},
    "typeof": {"desc": "C# 获取 Type 对象。", "syntax": "typeof(Type)", "example": "Type t = typeof(string);"},
    "yield": {"desc": "C# 迭代器中返回下一个元素。", "syntax": "yield return / yield break", "example": "yield return i * 2;"},
    "checked": {"desc": "C# 启用整数溢出检查。", "syntax": "checked { ... }", "example": "checked { int r = a * b; }"},
    "unchecked": {"desc": "C# 禁用整数溢出检查。", "syntax": "unchecked { ... }", "example": "unchecked { int r = a * b; }"},
}

# 各语言特有补充关键字（覆盖通用库未包含的）
_LANG_KEYWORD_EXTRA = {
    "python": {
        "lambda": {"desc": "定义匿名函数，常用于简短回调。", "syntax": "lambda args: expr", "example": "square = lambda x: x*x"},
        "pass": {"desc": "空语句占位符，语法上需要语句但不执行任何操作。", "syntax": "pass", "example": "class Empty: pass"},
        "with": {"desc": "上下文管理器，自动处理资源获取与释放。", "syntax": "with expr as var: ...", "example": "with open('f.txt') as f: data=f.read()"},
        "raise": {"desc": "主动抛出异常。", "syntax": "raise Exception(msg)", "example": "raise ValueError('invalid')"},
        "except": {"desc": "捕获并处理异常。", "syntax": "except ExceptionType as e: ...", "example": "except FileNotFoundError: print('missing')"},
        "finally": {"desc": "无论是否异常都执行的清理代码。", "syntax": "finally: ...", "example": "finally: conn.close()"},
        "global": {"desc": "在函数内声明使用全局变量。", "syntax": "global var", "example": "global count; count += 1"},
        "nonlocal": {"desc": "在嵌套函数中引用外层函数变量。", "syntax": "nonlocal var", "example": "nonlocal x; x += 1"},
        "del": {"desc": "删除变量、列表元素或字典键。", "syntax": "del name / del obj[key]", "example": "del d['key']"},
        "assert": {"desc": "断言条件为真，否则抛出 AssertionError。", "syntax": "assert cond, msg", "example": "assert x > 0, 'must be positive'"},
        "yield": {"desc": "生成器函数中返回值并暂停。", "syntax": "yield value", "example": "def gen(): yield 1; yield 2"},
        "async": {"desc": "定义异步函数（协程）。", "syntax": "async def name(): ...", "example": "async def fetch(): ..."},
        "await": {"desc": "等待协程完成。", "syntax": "await coro", "example": "data = await fetch()"},
        "try": {"desc": "异常处理开始。", "syntax": "try: ...", "example": "try: risky() except: handle()"},
    },
    "javascript": {
        "const": {"desc": "声明块级作用域常量，引用不可重新赋值。", "syntax": "const name = value;", "example": "const PI = 3.14;"},
        "class": {"desc": "ES6 类语法（原型继承的语法糖）。", "syntax": "class Name { ... }", "example": "class Person { constructor(n){this.name=n} }"},
        "extends": {"desc": "类继承。", "syntax": "class Child extends Parent", "example": "class Dog extends Animal { ... }"},
        "super": {"desc": "调用父类构造或方法。", "syntax": "super(args) / super.method()", "example": "super(name);"},
        "try": {"desc": "异常处理。", "syntax": "try { ... } catch(e) { ... }", "example": "try { JSON.parse(s) } catch(e) { ... }"},
        "catch": {"desc": "捕获异常。", "syntax": "catch (e) { ... }", "example": "catch (err) { console.error(err) }"},
        "finally": {"desc": "无论异常都执行。", "syntax": "finally { ... }", "example": "finally { cleanup(); }"},
        "throw": {"desc": "抛出异常。", "syntax": "throw expr;", "example": "throw new Error('fail');"},
        "typeof": {"desc": "获取值类型字符串。", "syntax": "typeof value", "example": "typeof 'hello' === 'string'"},
        "instanceof": {"desc": "判断原型链。", "syntax": "obj instanceof Ctor", "example": "[] instanceof Array"},
        "delete": {"desc": "删除对象属性。", "syntax": "delete obj.prop", "example": "delete user.age;"},
        "new": {"desc": "创建实例。", "syntax": "new Constructor()", "example": "const d = new Date();"},
        "this": {"desc": "当前执行上下文。", "syntax": "this", "example": "this.name = name;"},
        "void": {"desc": "求值并返回 undefined。", "syntax": "void expr", "example": "void 0"},
        "debugger": {"desc": "调试断点语句。", "syntax": "debugger;", "example": "debugger;"},
    },
    "c": {
        "auto": {"desc": "自动存储类（默认，可省略）。", "syntax": "auto type name;", "example": "auto int x = 0;"},
        "register": {"desc": "建议编译器将变量存入寄存器。", "syntax": "register type name;", "example": "register int i;"},
        "extern": {"desc": "声明外部链接的变量或函数。", "syntax": "extern type name;", "example": "extern int global_count;"},
        "static": {"desc": "静态存储，函数内保持值或文件内可见。", "syntax": "static type name;", "example": "static int calls = 0;"},
        "signed": {"desc": "有符号整数类型修饰。", "syntax": "signed int x;", "example": "signed char c;"},
        "unsigned": {"desc": "无符号整数类型修饰。", "syntax": "unsigned int x;", "example": "unsigned int len = 100;"},
        "short": {"desc": "短整数类型。", "syntax": "short int x;", "example": "short s = 32767;"},
        "long": {"desc": "长整数类型。", "syntax": "long int x;", "example": "long big = 1000000L;"},
        "struct": {"desc": "定义结构体。", "syntax": "struct Name { ... };", "example": "struct Point { int x; int y; };"},
        "enum": {"desc": "定义枚举。", "syntax": "enum Name { A, B, C };", "example": "enum Color { RED, GREEN, BLUE };"},
        "union": {"desc": "定义联合体。", "syntax": "union Name { ... };", "example": "union Data { int i; float f; };"},
        "typedef": {"desc": "类型别名。", "syntax": "typedef old new;", "example": "typedef unsigned int uint;"},
        "sizeof": {"desc": "获取字节大小。", "syntax": "sizeof(type/var)", "example": "size_t s = sizeof(int);"},
        "volatile": {"desc": "防止编译器优化该变量读写。", "syntax": "volatile type name;", "example": "volatile int flag = 0;"},
        "const": {"desc": "只读变量。", "syntax": "const type name = val;", "example": "const double PI = 3.14159;"},
        "void": {"desc": "无类型/无返回值。", "syntax": "void func() { ... }", "example": "void print() { printf('hi'); }"},
        "return": {"desc": "函数返回。", "syntax": "return value;", "example": "return 0;"},
        "goto": {"desc": "无条件跳转。", "syntax": "goto label;", "example": "goto cleanup;"},
        "case": {"desc": "switch 分支。", "syntax": "case value: ...", "example": "case 1: printf('one'); break;"},
        "default": {"desc": "switch 默认分支。", "syntax": "default: ...", "example": "default: printf('other');"},
        "break": {"desc": "跳出循环/switch。", "syntax": "break;", "example": "break;"},
        "continue": {"desc": "跳过本次循环。", "syntax": "continue;", "example": "continue;"},
        "if": {"desc": "条件判断。", "syntax": "if (cond) { ... }", "example": "if (x > 0) { ... }"},
        "else": {"desc": "条件分支。", "syntax": "else { ... }", "example": "else { ... }"},
        "for": {"desc": "for 循环。", "syntax": "for (init; cond; inc) { ... }", "example": "for (int i=0; i<n; i++) { ... }"},
        "while": {"desc": "while 循环。", "syntax": "while (cond) { ... }", "example": "while (n-- > 0) { ... }"},
        "do": {"desc": "do-while 循环。", "syntax": "do { ... } while (cond);", "example": "do { x++; } while (x < 10);"},
        "switch": {"desc": "多分支选择。", "syntax": "switch (expr) { ... }", "example": "switch (c) { case 'a': ... }"},
        "char": {"desc": "字符类型。", "syntax": "char c = 'A';", "example": "char c = getchar();"},
        "int": {"desc": "整数类型。", "syntax": "int x = 0;", "example": "int sum = 0;"},
        "float": {"desc": "单精度浮点。", "syntax": "float x = 1.0f;", "example": "float avg = 0.0f;"},
        "double": {"desc": "双精度浮点。", "syntax": "double x = 1.0;", "example": "double pi = 3.14159;"},
    },
    "cpp": {
        "auto": {"desc": "C++11 类型推断。", "syntax": "auto name = value;", "example": "auto v = std::vector<int>();"},
        "bool": {"desc": "布尔类型。", "syntax": "bool flag = true;", "example": "bool ok = false;"},
        "catch": {"desc": "捕获异常。", "syntax": "catch (const T& e) { ... }", "example": "catch (const std::exception& e) { ... }"},
        "throw": {"desc": "抛出异常。", "syntax": "throw expr;", "example": "throw std::runtime_error('fail');"},
        "try": {"desc": "异常处理块。", "syntax": "try { ... } catch(...) { ... }", "example": "try { risky(); } catch(...) { ... }"},
        "new": {"desc": "动态分配内存。", "syntax": "new Type(args)", "example": "int* p = new int[10];"},
        "delete": {"desc": "释放 new 分配的内存。", "syntax": "delete ptr; / delete[] arr;", "example": "delete[] p;"},
        "this": {"desc": "当前对象指针。", "syntax": "this->member", "example": "this->x = x;"},
        "friend": {"desc": "友元，允许访问私有成员。", "syntax": "friend class/func", "example": "friend void print(const A&);"},
        "inline": {"desc": "内联函数建议。", "syntax": "inline ret name(args) { ... }", "example": "inline int sq(int x){return x*x;}"},
        "explicit": {"desc": "禁止单参构造函数隐式转换。", "syntax": "explicit Ctor(args)", "example": "explicit A(int x);"},
        "mutable": {"desc": "允许 const 成员函数修改该成员。", "syntax": "mutable type name;", "example": "mutable int cache;"},
        "namespace": {"desc": "命名空间。", "syntax": "namespace name { ... }", "example": "namespace mylib { ... }"},
        "using": {"desc": "引入名称或命名空间别名。", "syntax": "using namespace std; / using T = ...", "example": "using std::string;"},
        "template": {"desc": "模板声明。", "syntax": "template <typename T>", "example": "template <typename T> T max(T a,T b)"},
        "typename": {"desc": "模板类型参数。", "syntax": "typename T", "example": "template <typename T> class Vec"},
        "class": {"desc": "定义类；也可作模板类型参数。", "syntax": "class Name { ... }", "example": "class Point { ... };"},
        "public": {"desc": "公开访问区段。", "syntax": "public:", "example": "public: void run();"},
        "protected": {"desc": "保护访问区段。", "syntax": "protected:", "example": "protected: int x;"},
        "private": {"desc": "私有访问区段。", "syntax": "private:", "example": "private: int data;"},
        "virtual": {"desc": "虚函数，运行时多态。", "syntax": "virtual ret name(args)", "example": "virtual void draw();"},
        "override": {"desc": "显式重写标记。", "syntax": "ret name(args) override", "example": "void draw() override { ... }"},
        "final": {"desc": "禁止继承/重写。", "syntax": "class final / method final", "example": "class Derived final : Base { }"},
        "constexpr": {"desc": "编译期常量表达式。", "syntax": "constexpr type name = val;", "example": "constexpr int SZ = 100;"},
        "consteval": {"desc": "C++20 立即函数，必须编译期求值。", "syntax": "consteval ret name(args)", "example": "consteval int sq(int n){return n*n;}"},
        "constinit": {"desc": "C++20 变量必须常量初始化。", "syntax": "constinit type name = val;", "example": "constinit int g = 0;"},
        "decltype": {"desc": "获取表达式类型。", "syntax": "decltype(expr)", "example": "decltype(a+b) c = a+b;"},
        "auto": {"desc": "类型推断。", "syntax": "auto x = expr;", "example": "auto it = v.begin();"},
        "range_for": {"desc": "范围 for 循环（语法，非关键字）。", "syntax": "for (auto& x : container)", "example": "for (int& x : arr) x++;"},
        "noexcept": {"desc": "标记函数不抛异常。", "syntax": "ret name() noexcept { ... }", "example": "void f() noexcept { ... }"},
        "static_assert": {"desc": "编译期断言。", "syntax": "static_assert(cond, msg)", "example": "static_assert(sizeof(int)==4);"},
        "alignas": {"desc": "指定对齐方式。", "syntax": "alignas(n) type name;", "example": "alignas(16) float data[4];"},
        "alignof": {"desc": "获取类型对齐要求。", "syntax": "alignof(type)", "example": "size_t a = alignof(int);"},
        "static_cast": {"desc": "静态类型转换。", "syntax": "static_cast<T>(expr)", "example": "double d = static_cast<double>(i);"},
        "dynamic_cast": {"desc": "运行时多态类型转换。", "syntax": "dynamic_cast<T*>(ptr)", "example": "auto* d = dynamic_cast<Derived*>(b);"},
        "reinterpret_cast": {"desc": "底层位模式重解释转换。", "syntax": "reinterpret_cast<T>(expr)", "example": "auto* p = reinterpret_cast<int*>(&d);"},
        "const_cast": {"desc": "添加或移除 const。", "syntax": "const_cast<T>(expr)", "example": "int* p = const_cast<int*>(&ci);"},
        "typeid": {"desc": "获取运行时类型信息。", "syntax": "typeid(expr)", "example": "if (typeid(*p) == typeid(D)) { ... }"},
        "export": {"desc": "C++20 模块导出。", "syntax": "export module name;", "example": "export module mylib;"},
        "module": {"desc": "C++20 模块声明。", "syntax": "module name;", "example": "module mylib;"},
        "import": {"desc": "C++20 导入模块。", "syntax": "import name;", "example": "import <iostream>;"},
        "concept": {"desc": "C++20 概念，约束模板参数。", "syntax": "concept Name = ...", "example": "concept Addable = requires(T a,T b){a+b;};"},
        "requires": {"desc": "C++20 requires 表达式/子句。", "syntax": "requires (T t) { ... }", "example": "requires (T t) { t.f(); }"},
        "co_await": {"desc": "C++20 协程等待。", "syntax": "co_await expr", "example": "auto v = co_await awaitable;"},
        "co_return": {"desc": "C++20 协程返回。", "syntax": "co_return value;", "example": "co_return 42;"},
        "co_yield": {"desc": "C++20 协程产出值。", "syntax": "co_yield value;", "example": "co_yield i;"},
        "char8_t": {"desc": "C++20 UTF-8 字符类型。", "syntax": "char8_t c = u8'A';", "example": "char8_t c = u8'x';"},
        "char16_t": {"desc": "UTF-16 字符类型。", "syntax": "char16_t c = u'A';", "example": "char16_t c = u'中';"},
        "char32_t": {"desc": "UTF-32 字符类型。", "syntax": "char32_t c = U'A';", "example": "char32_t c = U'中';"},
        "wchar_t": {"desc": "宽字符类型。", "syntax": "wchar_t c = L'A';", "example": "wchar_t c = L'中';"},
        "nullptr": {"desc": "空指针字面量。", "syntax": "nullptr", "example": "int* p = nullptr;"},
        "operator": {"desc": "重载运算符。", "syntax": "operator op(...)", "example": "bool operator==(const T&) const"},
        "sizeof...": {"desc": "获取参数包大小。", "syntax": "sizeof...(args)", "example": "size_t n = sizeof...(Args);"},
    },
    "java": {
        "byte": {"desc": "8 位有符号整数类型。", "syntax": "byte b = 10;", "example": "byte flag = 1;"},
        "short": {"desc": "16 位有符号整数类型。", "syntax": "short s = 100;", "example": "short count = 1000;"},
        "long": {"desc": "64 位有符号整数类型。", "syntax": "long n = 100L;", "example": "long big = 1000000000L;"},
        "byte": {"desc": "字节类型。", "syntax": "byte b;", "example": "byte[] data = new byte[1024];"},
        "void": {"desc": "无返回值。", "syntax": "void method() { ... }", "example": "void run() { ... }"},
        "new": {"desc": "创建对象。", "syntax": "new Class(args)", "example": "String s = new String('abc');"},
        "this": {"desc": "当前对象引用。", "syntax": "this.field / this.method()", "example": "this.name = name;"},
        "super": {"desc": "父类引用。", "syntax": "super.field / super(args)", "example": "super(name);"},
        "extends": {"desc": "类继承。", "syntax": "class Child extends Parent", "example": "class Dog extends Animal { }"},
        "implements": {"desc": "实现接口。", "syntax": "class C implements I1, I2", "example": "class R implements Runnable { }"},
        "interface": {"desc": "定义接口。", "syntax": "interface Name { ... }", "example": "interface Drawable { void draw(); }"},
        "abstract": {"desc": "抽象类/方法。", "syntax": "abstract class/method", "example": "abstract class Shape { abstract double area(); }"},
        "final": {"desc": "不可变/不可继承/不可重写。", "syntax": "final type/var/method/class", "example": "final double PI = 3.14;"},
        "static": {"desc": "静态成员，属于类。", "syntax": "static field/method", "example": "static int count = 0;"},
        "synchronized": {"desc": "线程同步。", "syntax": "synchronized(obj) { ... }", "example": "synchronized void inc() { n++; }"},
        "volatile": {"desc": "可见性修饰。", "syntax": "volatile type name;", "example": "volatile boolean running = true;"},
        "transient": {"desc": "不参与序列化。", "syntax": "transient type name;", "example": "transient Object cache;"},
        "native": {"desc": "本地方法。", "syntax": "native ret name(args);", "example": "native void start();"},
        "strictfp": {"desc": "严格浮点。", "syntax": "strictfp class/method", "example": "strictfp double calc() { ... }"},
        "package": {"desc": "声明包。", "syntax": "package com.example;", "example": "package com.app;"},
        "import": {"desc": "导入类/包。", "syntax": "import pkg.Class;", "example": "import java.util.List;"},
        "try": {"desc": "异常处理。", "syntax": "try { ... } catch(e) { ... }", "example": "try { f(); } catch(IOException e) { ... }"},
        "catch": {"desc": "捕获异常。", "syntax": "catch (ExceptionType e) { ... }", "example": "catch (Exception e) { e.printStackTrace(); }"},
        "finally": {"desc": "最终执行块。", "syntax": "finally { ... }", "example": "finally { close(); }"},
        "throw": {"desc": "抛出异常。", "syntax": "throw new Exception();", "example": "throw new IllegalArgumentException();"},
        "throws": {"desc": "声明可能抛出的异常。", "syntax": "void m() throws E1, E2", "example": "void read() throws IOException { }"},
        "instanceof": {"desc": "类型检查。", "syntax": "obj instanceof Type", "example": "if (obj instanceof String) { }"},
        "assert": {"desc": "断言。", "syntax": "assert cond : msg;", "example": "assert x > 0 : 'positive';"},
        "enum": {"desc": "枚举类。", "syntax": "enum Name { ... }", "example": "enum Day { MON, TUE, WED }"},
        "default": {"desc": "switch 默认分支；接口默认方法。", "syntax": "default: ... / default void m()", "example": "default void log() { ... }"},
        "switch": {"desc": "多分支选择。", "syntax": "switch(expr) { ... }", "example": "switch (n) { case 1: ... }"},
        "case": {"desc": "switch 分支。", "syntax": "case value: ...", "example": "case 'A': grade(); break;"},
        "break": {"desc": "跳出。", "syntax": "break;", "example": "break;"},
        "continue": {"desc": "继续循环。", "syntax": "continue;", "example": "continue;"},
        "return": {"desc": "返回。", "syntax": "return value;", "example": "return sum;"},
        "if": {"desc": "条件。", "syntax": "if (cond) { ... }", "example": "if (ok) { ... }"},
        "else": {"desc": "否则。", "syntax": "else { ... }", "example": "else { ... }"},
        "for": {"desc": "for 循环。", "syntax": "for (init; cond; inc) { ... }", "example": "for (int i=0; i<n; i++) { }"},
        "while": {"desc": "while 循环。", "syntax": "while (cond) { ... }", "example": "while (n-- > 0) { }"},
        "do": {"desc": "do-while 循环。", "syntax": "do { ... } while(cond);", "example": "do { x++; } while (x < 10);"},
        "goto": {"desc": "保留关键字（未使用）。", "syntax": "goto label;", "example": "// goto 未在 Java 中使用"},
        "const": {"desc": "保留关键字（未使用，用 final）。", "syntax": "const", "example": "// 用 final 代替 const"},
        "true": {"desc": "布尔真值字面量。", "syntax": "true", "example": "boolean ok = true;"},
        "false": {"desc": "布尔假值字面量。", "syntax": "false", "example": "boolean ok = false;"},
        "null": {"desc": "空引用。", "syntax": "null", "example": "String s = null;"},
    },
    "go": {
        "func": {"desc": "定义函数。", "syntax": "func name(args) ret { ... }", "example": "func add(a, b int) int { return a+b }"},
        "package": {"desc": "声明包。", "syntax": "package name", "example": "package main"},
        "import": {"desc": "导入包。", "syntax": "import \"path\" / import ( ... )", "example": "import \"fmt\""},
        "var": {"desc": "声明变量。", "syntax": "var name type = value", "example": "var count int = 0"},
        "const": {"desc": "声明常量。", "syntax": "const name = value", "example": "const Pi = 3.14"},
        "type": {"desc": "定义类型。", "syntax": "type Name underlying", "example": "type ID string"},
        "struct": {"desc": "定义结构体。", "syntax": "type Name struct { ... }", "example": "type Point struct { X, Y int }"},
        "interface": {"desc": "定义接口。", "syntax": "type Name interface { ... }", "example": "type Reader interface { Read() }"},
        "map": {"desc": "映射类型。", "syntax": "map[K]V", "example": "m := make(map[string]int)"},
        "chan": {"desc": "通道类型。", "syntax": "chan type", "example": "ch := make(chan int)"},
        "go": {"desc": "启动 goroutine。", "syntax": "go func() { ... }()", "example": "go handle(conn)"},
        "select": {"desc": "多路通道等待。", "syntax": "select { case ...: ... }", "example": "select { case v := <-ch: ... }"},
        "range": {"desc": "遍历集合。", "syntax": "for k, v := range coll", "example": "for i, v := range arr { }"},
        "defer": {"desc": "延迟执行。", "syntax": "defer func()", "example": "defer file.Close()"},
        "go": {"desc": "并发启动。", "syntax": "go f()", "example": "go worker()"},
        "break": {"desc": "跳出循环/select。", "syntax": "break", "example": "break"},
        "continue": {"desc": "继续循环。", "syntax": "continue", "example": "continue"},
        "fallthrough": {"desc": "switch 中穿透到下一个 case。", "syntax": "fallthrough", "example": "case 1: fallthrough"},
        "default": {"desc": "switch/select 默认分支。", "syntax": "default: ...", "example": "default: fmt.Println('other')"},
        "case": {"desc": "switch/select 分支。", "syntax": "case expr: ...", "example": "case 'a': ..."},
        "switch": {"desc": "分支选择。", "syntax": "switch expr { ... }", "example": "switch x { case 1: ... }"},
        "if": {"desc": "条件判断。", "syntax": "if cond { ... }", "example": "if err != nil { ... }"},
        "else": {"desc": "否则分支。", "syntax": "else { ... }", "example": "else { ... }"},
        "for": {"desc": "循环（Go 唯一循环关键字）。", "syntax": "for init; cond; inc { ... }", "example": "for i := 0; i < n; i++ { }"},
        "return": {"desc": "函数返回。", "syntax": "return values", "example": "return sum, nil"},
        "nil": {"desc": "空值（指针/切片/map/通道/接口/函数）。", "syntax": "nil", "example": "var p *int = nil"},
        "true": {"desc": "布尔真。", "syntax": "true", "example": "ok := true"},
        "false": {"desc": "布尔假。", "syntax": "false", "example": "ok := false"},
        "iota": {"desc": "常量生成器，每行自增。", "syntax": "iota", "example": "const ( A = iota; B; C )"},
    },
    "rust": {
        "fn": {"desc": "定义函数。", "syntax": "fn name(args) -> ret { ... }", "example": "fn add(a: i32, b: i32) -> i32 { a + b }"},
        "let": {"desc": "声明变量（默认不可变）。", "syntax": "let name = value;", "example": "let x = 5;"},
        "mut": {"desc": "标记可变。", "syntax": "let mut name = value;", "example": "let mut count = 0;"},
        "pub": {"desc": "公开可见。", "syntax": "pub fn/struct/mod", "example": "pub fn run() { }"},
        "impl": {"desc": "实现方法或 trait。", "syntax": "impl Type { ... } / impl Trait for Type", "example": "impl Point { fn new() -> Self }"},
        "trait": {"desc": "定义 trait（接口）。", "syntax": "trait Name { ... }", "example": "trait Draw { fn draw(&self); }"},
        "mod": {"desc": "定义模块。", "syntax": "mod name { ... }", "example": "mod utils { }"},
        "use": {"desc": "导入名称。", "syntax": "use path::Item;", "example": "use std::collections::HashMap;"},
        "crate": {"desc": "当前 crate 根路径。", "syntax": "crate::path", "example": "use crate::helper;"},
        "self": {"desc": "当前模块/实例。", "syntax": "self / &self / &mut self", "example": "fn area(&self) -> f64"},
        "Self": {"desc": "实现类型别名。", "syntax": "Self", "example": "fn new() -> Self { Self { } }"},
        "match": {"desc": "模式匹配。", "syntax": "match expr { ... }", "example": "match x { 0 => 'zero', _ => 'other' }"},
        "loop": {"desc": "无限循环。", "syntax": "loop { ... }", "example": "loop { if done { break; } }"},
        "while": {"desc": "条件循环。", "syntax": "while cond { ... }", "example": "while n > 0 { n -= 1; }"},
        "for": {"desc": "迭代循环。", "syntax": "for pat in iter { ... }", "example": "for x in 0..10 { }"},
        "if": {"desc": "条件（也是表达式）。", "syntax": "if cond { ... } else { ... }", "example": "let m = if x > 0 { '+' } else { '-' }"},
        "else": {"desc": "否则分支。", "syntax": "else { ... }", "example": "else { }"},
        "break": {"desc": "跳出循环（可带值）。", "syntax": "break / break value", "example": "break result;"},
        "continue": {"desc": "继续循环。", "syntax": "continue", "example": "continue;"},
        "return": {"desc": "函数返回。", "syntax": "return value;", "example": "return 0;"},
        "struct": {"desc": "定义结构体。", "syntax": "struct Name { ... }", "example": "struct Point { x: f64, y: f64 }"},
        "enum": {"desc": "定义枚举（可带数据）。", "syntax": "enum Name { A, B(T) }", "example": "enum Option<T> { Some(T), None }"},
        "union": {"desc": "定义联合体（unsafe 访问）。", "syntax": "union Name { ... }", "example": "union Data { i: i32, f: f32 }"},
        "type": {"desc": "类型别名。", "syntax": "type Name = underlying;", "example": "type Result<T> = std::result::Result<T, Err>;"},
        "where": {"desc": "trait 约束子句。", "syntax": "where T: Trait", "example": "fn f<T>(x: T) where T: Clone"},
        "move": {"desc": "闭包捕获所有权。", "syntax": "move |args| { ... }", "example": "let c = move || x + 1;"},
        "dyn": {"desc": "动态 trait 对象。", "syntax": "dyn Trait", "example": "Box<dyn Draw>"},
        "impl": {"desc": "impl Trait 语法（参数/返回位置）。", "syntax": "impl Trait", "example": "fn f() -> impl Iterator<Item=i32>"},
        "async": {"desc": "异步函数。", "syntax": "async fn name() { ... }", "example": "async fn fetch() { }"},
        "await": {"desc": "等待 Future。", "syntax": "expr.await", "example": "let r = fetch().await;"},
        "unsafe": {"desc": "不安全代码块/trait。", "syntax": "unsafe { ... } / unsafe fn", "example": "unsafe { *p = 1; }"},
        "extern": {"desc": "外部函数接口/块。", "syntax": "extern \"C\" { ... }", "example": "extern \"C\" { fn printf(...); }"},
        "macro_rules": {"desc": "声明宏定义。", "syntax": "macro_rules! name { ... }", "example": "macro_rules! say { () => { println!() }"},
        "ref": {"desc": "模式中绑定引用。", "syntax": "ref name", "example": "let ref x = value;"},
        "static": {"desc": "全局静态变量。", "syntax": "static NAME: type = value;", "example": "static COUNT: AtomicI32 = AtomicI32::new(0);"},
        "const": {"desc": "编译期常量。", "syntax": "const NAME: type = value;", "example": "const MAX: usize = 100;"},
        "as": {"desc": "类型转换/重命名/原始指针转换。", "syntax": "expr as Type", "example": "let f = x as f64;"},
        "in": {"desc": "for 循环中使用；模式中范围。", "syntax": "for x in iter", "example": "for i in 0..10 { }"},
        "where": {"desc": "约束子句。", "syntax": "where T: Trait", "example": "where T: Debug"},
        "super": {"desc": "父模块路径。", "syntax": "super::path", "example": "use super::helper;"},
        "true": {"desc": "布尔真。", "syntax": "true", "example": "let ok = true;"},
        "false": {"desc": "布尔假。", "syntax": "false", "example": "let ok = false;"},
    },
    "csharp": {
        "using": {"desc": "引入命名空间或资源释放。", "syntax": "using Namespace; / using (var r=...) { }", "example": "using System.IO;"},
        "namespace": {"desc": "声明命名空间。", "syntax": "namespace Name { ... }", "example": "namespace MyApp.Models"},
        "class": {"desc": "定义类。", "syntax": "class Name { ... }", "example": "class Person { }"},
        "struct": {"desc": "定义值类型结构体。", "syntax": "struct Name { ... }", "example": "struct Point { public int X; }"},
        "interface": {"desc": "定义接口。", "syntax": "interface Name { ... }", "example": "interface IDrawable { void Draw(); }"},
        "enum": {"desc": "定义枚举。", "syntax": "enum Name { ... }", "example": "enum Color { Red, Green }"},
        "delegate": {"desc": "定义委托类型。", "syntax": "delegate ret Name(args);", "example": "delegate int Handler(int x);"},
        "event": {"desc": "声明事件。", "syntax": "event Handler Name;", "example": "public event EventHandler Click;"},
        "public": {"desc": "公开访问。", "syntax": "public member", "example": "public void Run() { }"},
        "private": {"desc": "私有访问。", "syntax": "private member", "example": "private int _id;"},
        "protected": {"desc": "保护访问。", "syntax": "protected member", "example": "protected void Init() { }"},
        "internal": {"desc": "程序集内可见。", "syntax": "internal member", "example": "internal class Helper { }"},
        "static": {"desc": "静态成员。", "syntax": "static member", "example": "static int Count = 0;"},
        "readonly": {"desc": "只读字段。", "syntax": "readonly type name;", "example": "readonly int _id;"},
        "const": {"desc": "编译期常量。", "syntax": "const type NAME = val;", "example": "const int Max = 100;"},
        "sealed": {"desc": "密封类，不可继承。", "syntax": "sealed class Name", "example": "sealed class Util { }"},
        "abstract": {"desc": "抽象类/方法。", "syntax": "abstract class/method", "example": "public abstract double Area();"},
        "virtual": {"desc": "虚方法。", "syntax": "virtual ret name(args)", "example": "public virtual void Draw() { }"},
        "override": {"desc": "重写方法。", "syntax": "override ret name(args)", "example": "public override void Draw() { }"},
        "new": {"desc": "创建对象；隐藏父类成员。", "syntax": "new Type(args) / new member", "example": "var p = new Person();"},
        "this": {"desc": "当前实例；扩展方法首参。", "syntax": "this.member / this type", "example": "this.Name = name;"},
        "base": {"desc": "父类引用。", "syntax": "base.member / base(args)", "example": "base(name);"},
        "void": {"desc": "无返回值。", "syntax": "void method() { }", "example": "void Print() { }"},
        "var": {"desc": "类型推断。", "syntax": "var name = value;", "example": "var list = new List<int>();"},
        "dynamic": {"desc": "动态类型，运行时解析。", "syntax": "dynamic name = value;", "example": "dynamic obj = GetObject();"},
        "object": {"desc": "所有类型的基类。", "syntax": "object name;", "example": "object data = 42;"},
        "string": {"desc": "字符串类型。", "syntax": "string s = \"...\";", "example": "string name = \"Tom\";"},
        "int": {"desc": "整数类型。", "syntax": "int x = 0;", "example": "int count = 0;"},
        "long": {"desc": "64位整数。", "syntax": "long x = 0L;", "example": "long big = 1000000L;"},
        "float": {"desc": "单精度浮点。", "syntax": "float x = 0.0f;", "example": "float rate = 0.5f;"},
        "double": {"desc": "双精度浮点。", "syntax": "double x = 0.0;", "example": "double pi = 3.14;"},
        "decimal": {"desc": "高精度十进制数。", "syntax": "decimal x = 0.0m;", "example": "decimal price = 9.99m;"},
        "bool": {"desc": "布尔类型。", "syntax": "bool flag = true;", "example": "bool ok = true;"},
        "char": {"desc": "字符类型。", "syntax": "char c = 'A';", "example": "char grade = 'A';"},
        "byte": {"desc": "字节类型。", "syntax": "byte b = 0;", "example": "byte[] data = new byte[10];"},
        "sbyte": {"desc": "有符号字节。", "syntax": "sbyte b = 0;", "example": "sbyte signed = -1;"},
        "short": {"desc": "短整数。", "syntax": "short s = 0;", "example": "short n = 100;"},
        "ushort": {"desc": "无符号短整数。", "syntax": "ushort s = 0;", "example": "ushort port = 8080;"},
        "uint": {"desc": "无符号整数。", "syntax": "uint x = 0;", "example": "uint hash = 0;"},
        "ulong": {"desc": "无符号长整数。", "syntax": "ulong x = 0;", "example": "ulong big = 0;"},
        "if": {"desc": "条件判断。", "syntax": "if (cond) { }", "example": "if (ok) { }"},
        "else": {"desc": "否则。", "syntax": "else { }", "example": "else { }"},
        "switch": {"desc": "多分支选择。", "syntax": "switch (expr) { }", "example": "switch (n) { case 1: ... }"},
        "case": {"desc": "分支标签。", "syntax": "case value: ...", "example": "case 1: break;"},
        "default": {"desc": "默认分支。", "syntax": "default: ...", "example": "default: break;"},
        "while": {"desc": "while 循环。", "syntax": "while (cond) { }", "example": "while (n-- > 0) { }"},
        "do": {"desc": "do-while 循环。", "syntax": "do { } while (cond);", "example": "do { x++; } while (x < 10);"},
        "for": {"desc": "for 循环。", "syntax": "for (init; cond; inc) { }", "example": "for (int i=0; i<n; i++) { }"},
        "foreach": {"desc": "遍历集合。", "syntax": "foreach (var x in coll) { }", "example": "foreach (var item in list) { }"},
        "break": {"desc": "跳出。", "syntax": "break;", "example": "break;"},
        "continue": {"desc": "继续。", "syntax": "continue;", "example": "continue;"},
        "goto": {"desc": "跳转。", "syntax": "goto label;", "example": "goto cleanup;"},
        "return": {"desc": "返回。", "syntax": "return value;", "example": "return 0;"},
        "throw": {"desc": "抛出异常。", "syntax": "throw new Exception();", "example": "throw new ArgumentException();"},
        "try": {"desc": "异常处理。", "syntax": "try { } catch { }", "example": "try { f(); } catch (Exception e) { }"},
        "catch": {"desc": "捕获异常。", "syntax": "catch (Exception e) { }", "example": "catch (IOException e) { }"},
        "finally": {"desc": "最终执行。", "syntax": "finally { }", "example": "finally { close(); }"},
        "checked": {"desc": "溢出检查。", "syntax": "checked { }", "example": "checked { int r = a*b; }"},
        "unchecked": {"desc": "不检查溢出。", "syntax": "unchecked { }", "example": "unchecked { int r = a*b; }"},
        "unsafe": {"desc": "不安全上下文。", "syntax": "unsafe { }", "example": "unsafe { int* p = &x; }"},
        "fixed": {"desc": "固定内存。", "syntax": "fixed (type* p = &arr[0]) { }", "example": "fixed (int* p = arr) { }"},
        "stackalloc": {"desc": "栈分配。", "syntax": "stackalloc type[n]", "example": "int* buf = stackalloc int[256];"},
        "lock": {"desc": "线程锁。", "syntax": "lock (obj) { }", "example": "lock (_sync) { n++; }"},
        "async": {"desc": "异步方法。", "syntax": "async Task method() { }", "example": "async Task<string> ReadAsync()"},
        "await": {"desc": "等待异步。", "syntax": "await task", "example": "var data = await ReadAsync();"},
        "yield": {"desc": "迭代器返回。", "syntax": "yield return / yield break", "example": "yield return i * 2;"},
        "partial": {"desc": "分部类/方法。", "syntax": "partial class Name", "example": "partial class Form1 { }"},
        "operator": {"desc": "重载运算符。", "syntax": "operator op(...)", "example": "public static Point operator +(Point a, Point b)"},
        "explicit": {"desc": "显式转换运算符。", "syntax": "explicit operator Type(expr)", "example": "public static explicit operator int(Foo f)"},
        "implicit": {"desc": "隐式转换运算符。", "syntax": "implicit operator Type(expr)", "example": "public static implicit operator Foo(int x)"},
        "params": {"desc": "可变参数。", "syntax": "params type[] name", "example": "int Sum(params int[] nums)"},
        "ref": {"desc": "引用参数。", "syntax": "ref type name", "example": "void Swap(ref int a, ref int b)"},
        "out": {"desc": "输出参数。", "syntax": "out type name", "example": "bool TryParse(string s, out int n)"},
        "in": {"desc": "只读引用参数。", "syntax": "in type name", "example": "void Calc(in Point p)"},
        "is": {"desc": "类型检查/模式匹配。", "syntax": "expr is Type", "example": "if (obj is string s) { }"},
        "as": {"desc": "安全转换。", "syntax": "expr as Type", "example": "var s = obj as string;"},
        "sizeof": {"desc": "获取大小。", "syntax": "sizeof(type)", "example": "int s = sizeof(int);"},
        "typeof": {"desc": "获取 Type。", "syntax": "typeof(Type)", "example": "Type t = typeof(string);"},
        "nameof": {"desc": "获取名称字符串。", "syntax": "nameof(expr)", "example": "nameof(Person.Name)"},
        "true": {"desc": "布尔真。", "syntax": "true", "example": "bool ok = true;"},
        "false": {"desc": "布尔假。", "syntax": "false", "example": "bool ok = false;"},
        "null": {"desc": "空引用。", "syntax": "null", "example": "string s = null;"},
        "value": {"desc": "setter 隐式参数。", "syntax": "value", "example": "set { _x = value; }"},
        "get": {"desc": "属性 getter。", "syntax": "get { }", "example": "public int X { get; set; }"},
        "set": {"desc": "属性 setter。", "syntax": "set { }", "example": "public int X { get; set; }"},
        "when": {"desc": "异常/模式过滤条件。", "syntax": "when (cond)", "example": "catch (Exception e) when (e is IOException)"},
        "record": {"desc": "C# 9 record 类型。", "syntax": "record Name(props)", "example": "public record Person(string Name, int Age);"},
        "init": {"desc": "C# 9 init-only 属性。", "syntax": "init { }", "example": "public int X { get; init; }"},
        "with": {"desc": "C# 9 with 表达式（非破坏性修改）。", "syntax": "obj with { prop = val }", "example": "var p2 = p with { Age = 30 };"},
        "global": {"desc": "C# 10 全局 using。", "syntax": "global using Namespace;", "example": "global using System.Linq;"},
        "file": {"desc": "C# 11 文件局部类型。", "syntax": "file class Name", "example": "file class Helper { }"},
        "required": {"desc": "C# 11 必填属性。", "syntax": "required type prop", "example": "public required string Name { get; set; }"},
        "scoped": {"desc": "C# 11 scoped ref 参数。", "syntax": "scoped ref type", "example": "void M(scoped ref int x)"},
    },
    "swift": {
        "func": {"desc": "定义函数。", "syntax": "func name(args) -> ret { ... }", "example": "func add(a: Int, b: Int) -> Int { a+b }"},
        "var": {"desc": "可变变量。", "syntax": "var name = value", "example": "var count = 0"},
        "let": {"desc": "不可变常量。", "syntax": "let name = value", "example": "let pi = 3.14"},
        "class": {"desc": "引用类型类。", "syntax": "class Name { ... }", "example": "class Person { var name: String }"},
        "struct": {"desc": "值类型结构体。", "syntax": "struct Name { ... }", "example": "struct Point { var x, y: Double }"},
        "enum": {"desc": "枚举（可带关联值/原始值）。", "syntax": "enum Name { ... }", "example": "enum Direction { case north, south }"},
        "protocol": {"desc": "协议（接口）。", "syntax": "protocol Name { ... }", "example": "protocol Drawable { func draw() }"},
        "extension": {"desc": "扩展已有类型。", "syntax": "extension Type { ... }", "example": "extension Int { var sq: Int { self*self } }"},
        "init": {"desc": "初始化方法。", "syntax": "init(args) { ... }", "example": "init(name: String) { ... }"},
        "deinit": {"desc": "反初始化。", "syntax": "deinit { ... }", "example": "deinit { cleanup() }"},
        "import": {"desc": "导入模块。", "syntax": "import Module", "example": "import UIKit"},
        "if": {"desc": "条件（也是表达式）。", "syntax": "if cond { ... } else { ... }", "example": "if x > 0 { ... }"},
        "else": {"desc": "否则。", "syntax": "else { ... }", "example": "else { ... }"},
        "guard": {"desc": "提前退出条件。", "syntax": "guard cond else { ... }", "example": "guard let x = opt else { return }"},
        "switch": {"desc": "模式匹配（必须完备，无隐式穿透）。", "syntax": "switch x { ... }", "example": "switch x { case 0: print('zero'); default: ... }"},
        "case": {"desc": "switch 分支。", "syntax": "case pattern: ...", "example": "case 1...5: print('small')"},
        "default": {"desc": "默认分支。", "syntax": "default: ...", "example": "default: break"},
        "for": {"desc": "for-in 循环。", "syntax": "for x in sequence { ... }", "example": "for i in 0..<10 { }"},
        "while": {"desc": "while 循环。", "syntax": "while cond { ... }", "example": "while n > 0 { n -= 1 }"},
        "repeat": {"desc": "repeat-while 循环（类似 do-while）。", "syntax": "repeat { ... } while cond", "example": "repeat { x++ } while x < 10"},
        "break": {"desc": "跳出循环/switch。", "syntax": "break", "example": "break"},
        "continue": {"desc": "继续循环。", "syntax": "continue", "example": "continue"},
        "fallthrough": {"desc": "switch 中穿透到下一个 case。", "syntax": "fallthrough", "example": "case 1: fallthrough"},
        "return": {"desc": "函数返回。", "syntax": "return value", "example": "return 0"},
        "throw": {"desc": "抛出错误。", "syntax": "throw error", "example": "throw AppError.invalid"},
        "throws": {"desc": "标记函数可抛错。", "syntax": "func name() throws -> ret", "example": "func load() throws -> Data"},
        "rethrows": {"desc": "仅参数函数抛错时才抛错。", "syntax": "func name(_ f: () throws -> ()) rethrows", "example": "func map(_ f: (T) throws -> U) rethrows -> [U]"},
        "try": {"desc": "调用可抛错函数。", "syntax": "try expr / try? / try!", "example": "let data = try load()"},
        "catch": {"desc": "捕获错误。", "syntax": "catch { ... }", "example": "do { try f() } catch { log() }"},
        "defer": {"desc": "延迟到作用域结束执行。", "syntax": "defer { ... }", "example": "defer { file.close() }"},
        "inout": {"desc": "可修改的引用参数。", "syntax": "inout type", "example": "func swap(_ a: inout Int, _ b: inout Int)"},
        "mutating": {"desc": "标记 struct/enum 方法可修改自身。", "syntax": "mutating func name()", "example": "mutating func add(_ n: Int)"},
        "nonmutating": {"desc": "标记方法不修改自身（通常用于 setter）。", "syntax": "nonmutating func name()", "example": "nonmutating func reset()"},
        "convenience": {"desc": "便利初始化方法。", "syntax": "convenience init(args)", "example": "convenience init() { self.init(x: 0) }"},
        "required": {"desc": "要求子类必须实现的初始化。", "syntax": "required init(args)", "example": "required init?(coder: NSCoder)"},
        "override": {"desc": "重写父类成员。", "syntax": "override func/var", "example": "override func draw() { }"},
        "static": {"desc": "类型级成员（值类型）。", "syntax": "static func/var", "example": "static var count = 0"},
        "class": {"desc": "类型级成员（引用类型，可重写）。", "syntax": "class func/var", "example": "class func description() -> String"},
        "final": {"desc": "禁止继承/重写。", "syntax": "final class/method", "example": "final class Util { }"},
        "lazy": {"desc": "延迟存储属性。", "syntax": "lazy var name = expr", "example": "lazy var formatter = DateFormatter()"},
        "weak": {"desc": "弱引用（不持有对象，可置 nil）。", "syntax": "weak var name: Type?", "example": "weak var delegate: Delegate?"},
        "unowned": {"desc": "无主引用（不持有，假定非空）。", "syntax": "unowned let/var name", "example": "unowned let owner: Person"},
        "didSet": {"desc": "属性观察器，设置后。", "syntax": "didSet { ... }", "example": "var x = 0 { didSet { print(x) } }"},
        "willSet": {"desc": "属性观察器，设置前。", "syntax": "willSet { ... }", "example": "var x = 0 { willSet { print(newValue) } }"},
        "subscript": {"desc": "下标访问。", "syntax": "subscript(idx: Int) -> T { ... }", "example": "subscript(i: Int) -> Element"},
        "typealias": {"desc": "类型别名。", "syntax": "typealias New = Old", "example": "typealias JSON = [String: Any]"},
        "associatedtype": {"desc": "协议关联类型。", "syntax": "associatedtype Name", "example": "associatedtype Element"},
        "operator": {"desc": "运算符函数。", "syntax": "operator func", "example": "func + (l: Point, r: Point) -> Point"},
        "infix": {"desc": "中缀运算符声明。", "syntax": "infix operator Name", "example": "infix operator ++"},
        "prefix": {"desc": "前缀运算符声明。", "syntax": "prefix operator Name", "example": "prefix operator ++"},
        "postfix": {"desc": "后缀运算符声明。", "syntax": "postfix operator Name", "example": "postfix operator ++"},
        "precedencegroup": {"desc": "运算符优先级组。", "syntax": "precedencegroup Name { ... }", "example": "precedencegroup Comparison { ... }"},
        "where": {"desc": "泛型约束/模式过滤。", "syntax": "where condition", "example": "func f<T>(_ x: T) where T: Equatable"},
        "indirect": {"desc": "枚举递归 case 标记。", "syntax": "indirect case Name", "example": "indirect case node(T, List)"},
        "open": {"desc": "模块外可继承/重写（最高访问级）。", "syntax": "open class/method", "example": "open class Base { }"},
        "public": {"desc": "模块外可访问但不可继承。", "syntax": "public class/member", "example": "public struct Point { }"},
        "internal": {"desc": "模块内可见（默认）。", "syntax": "internal member", "example": "internal var cache = ..."},
        "fileprivate": {"desc": "当前文件内可见。", "syntax": "fileprivate member", "example": "fileprivate var x = 0"},
        "private": {"desc": "当前作用域内可见。", "syntax": "private member", "example": "private var _id = 0"},
        "get": {"desc": "属性 getter。", "syntax": "get { ... }", "example": "var area: Double { get { w*h } }"},
        "set": {"desc": "属性 setter。", "syntax": "set { ... }", "example": "var x: Int { set { _x = newValue } }"},
        "true": {"desc": "布尔真。", "syntax": "true", "example": "let ok = true"},
        "false": {"desc": "布尔假。", "syntax": "false", "example": "let ok = false"},
        "nil": {"desc": "可选类型空值。", "syntax": "nil", "example": "var name: String? = nil"},
        "self": {"desc": "当前实例/类型。", "syntax": "self / Self", "example": "self.name = name"},
        "super": {"desc": "父类引用。", "syntax": "super.method()", "example": "super.init(name: name)"},
        "Any": {"desc": "任意类型（包括函数类型）。", "syntax": "Any", "example": "var x: Any = 42"},
        "AnyObject": {"desc": "任意类实例类型。", "syntax": "AnyObject", "example": "var obj: AnyObject = Person()"},
        "Self": {"desc": "当前类型（协议/类中）。", "syntax": "Self", "example": "static func make() -> Self"},
    },
    "kotlin": {
        "package": {"desc": "声明包。", "syntax": "package com.example", "example": "package com.app"},
        "import": {"desc": "导入。", "syntax": "import pkg.Class", "example": "import java.util.List"},
        "fun": {"desc": "定义函数。", "syntax": "fun name(args): ret { ... }", "example": "fun add(a: Int, b: Int) = a + b"},
        "val": {"desc": "只读变量。", "syntax": "val name = value", "example": "val pi = 3.14"},
        "var": {"desc": "可变变量。", "syntax": "var name = value", "example": "var count = 0"},
        "class": {"desc": "定义类。", "syntax": "class Name(args) { ... }", "example": "class Person(val name: String)"},
        "interface": {"desc": "定义接口。", "syntax": "interface Name { ... }", "example": "interface Drawable { fun draw() }"},
        "object": {"desc": "单例对象/对象表达式。", "syntax": "object Name { ... } / object : Super() { }", "example": "object Config { ... }"},
        "companion": {"desc": "伴生对象（类内静态成员）。", "syntax": "companion object { ... }", "example": "companion object { const val TAG = 'X' }"},
        "data": {"desc": "数据类（自动生成 equals/hashCode/toString/copy）。", "syntax": "data class Name(val p: T)", "example": "data class User(val name: String)"},
        "sealed": {"desc": "密封类（限制继承层级）。", "syntax": "sealed class Name", "example": "sealed class Result"},
        "enum": {"desc": "枚举类。", "syntax": "enum class Name { ... }", "example": "enum class Color { RED, GREEN }"},
        "annotation": {"desc": "注解类。", "syntax": "annotation class Name", "example": "annotation class Inject"},
        "abstract": {"desc": "抽象类/方法。", "syntax": "abstract class/member", "example": "abstract class Shape"},
        "open": {"desc": "可被继承/重写（Kotlin 默认 final）。", "syntax": "open class/member", "example": "open class Base { open fun f() }"},
        "final": {"desc": "不可继承/重写（默认）。", "syntax": "final class/member", "example": "final class Util"},
        "override": {"desc": "重写父类成员。", "syntax": "override fun/val", "example": "override fun f() { }"},
        "private": {"desc": "文件内/类内私有。", "syntax": "private member", "example": "private var x = 0"},
        "protected": {"desc": "类及子类可见。", "syntax": "protected member", "example": "protected var x = 0"},
        "internal": {"desc": "模块内可见。", "syntax": "internal member", "example": "internal val cache = ..."},
        "public": {"desc": "公开可见（默认）。", "syntax": "public member", "example": "public fun f() { }"},
        "constructor": {"desc": "构造函数声明。", "syntax": "constructor(args)", "example": "constructor(name: String): this()"},
        "init": {"desc": "初始化块。", "syntax": "init { ... }", "example": "init { require(age > 0) }"},
        "this": {"desc": "当前实例/构造函数委托。", "syntax": "this / this(args)", "example": "this.name = name"},
        "super": {"desc": "父类引用。", "syntax": "super.method() / super(args)", "example": "super(name)"},
        "if": {"desc": "条件（也是表达式）。", "syntax": "if (cond) ... else ...", "example": "val m = if (x>0) '+' else '-'"},
        "else": {"desc": "否则。", "syntax": "else ...", "example": "else { }"},
        "when": {"desc": "分支表达式（增强版 switch）。", "syntax": "when (x) { ... }", "example": "when (x) { 1 -> 'one' else -> 'other' }"},
        "for": {"desc": "for 循环。", "syntax": "for (x in iterable) { ... }", "example": "for (i in 0..9) { }"},
        "while": {"desc": "while 循环。", "syntax": "while (cond) { ... }", "example": "while (n-- > 0) { }"},
        "do": {"desc": "do-while 循环。", "syntax": "do { ... } while (cond)", "example": "do { x++ } while (x < 10)"},
        "break": {"desc": "跳出循环。", "syntax": "break", "example": "break"},
        "continue": {"desc": "继续循环。", "syntax": "continue", "example": "continue"},
        "return": {"desc": "函数返回。", "syntax": "return value", "example": "return 0"},
        "throw": {"desc": "抛出异常。", "syntax": "throw Exception()", "example": "throw IllegalArgumentException()"},
        "try": {"desc": "异常处理（也是表达式）。", "syntax": "try { ... } catch(e) { ... }", "example": "try { f() } catch(e: Exception) { }"},
        "catch": {"desc": "捕获异常。", "syntax": "catch (e: Type) { ... }", "example": "catch (e: IOException) { }"},
        "finally": {"desc": "最终执行。", "syntax": "finally { ... }", "example": "finally { close() }"},
        "is": {"desc": "类型检查（智能转换）。", "syntax": "expr is Type", "example": "if (obj is String) { ... }"},
        "!is": {"desc": "类型否定检查。", "syntax": "expr !is Type", "example": "if (obj !is String) { }"},
        "as": {"desc": "类型转换（不安全，失败抛异常）。", "syntax": "expr as Type", "example": "val s = obj as String"},
        "as?": {"desc": "安全类型转换（失败返回 null）。", "syntax": "expr as? Type", "example": "val s = obj as? String"},
        "in": {"desc": "成员检查/范围/循环。", "syntax": "x in collection / for x in ...", "example": "if (x in 1..10) { }"},
        "!in": {"desc": "非成员检查。", "syntax": "x !in collection", "example": "if (x !in list) { }"},
        "null": {"desc": "空值（Kotlin 用 ? 标记可空类型，null 是字面量）。", "syntax": "null", "example": "var s: String? = null"},
        "true": {"desc": "布尔真。", "syntax": "true", "example": "val ok = true"},
        "false": {"desc": "布尔假。", "syntax": "false", "example": "val ok = false"},
        "typealias": {"desc": "类型别名。", "syntax": "typealias New = Old", "example": "typealias JSON = Map<String, Any>"},
        "by": {"desc": "委托（类委托/属性委托）。", "syntax": "by delegate", "example": "val p by lazy { ... }"},
        "lazy": {"desc": "懒加载委托（常用，非关键字）。", "syntax": "by lazy { ... }", "example": "val x by lazy { compute() }"},
        "lateinit": {"desc": "延迟初始化非空属性。", "syntax": "lateinit var name: Type", "example": "lateinit var api: ApiService"},
        "suspend": {"desc": "挂起函数（协程）。", "syntax": "suspend fun name() { ... }", "example": "suspend fun load(): Data"},
        "inline": {"desc": "内联函数。", "syntax": "inline fun name()", "example": "inline fun measure(block: () -> Unit)"},
        "noinline": {"desc": "禁止内联某个 lambda 参数。", "syntax": "noinline param", "example": "inline fun f(noinline g: () -> Unit)"},
        "crossinline": {"desc": "禁止非局部返回。", "syntax": "crossinline param", "example": "inline fun f(crossinline g: () -> Unit)"},
        "reified": {"desc": "具体化类型参数（需 inline）。", "syntax": "reified T", "example": "inline fun <reified T> check()"},
        "tailrec": {"desc": "尾递归优化。", "syntax": "tailrec fun name()", "example": "tailrec fun fact(n: Int, acc: Int): Int"},
        "infix": {"desc": "中缀函数。", "syntax": "infix fun name()", "example": "infix fun Int.and(other: Int)"},
        "operator": {"desc": "运算符重载。", "syntax": "operator fun name()", "example": "operator fun plus(other: Point)"},
        "vararg": {"desc": "可变参数。", "syntax": "vararg name: Type", "example": "fun sum(vararg nums: Int)"},
        "out": {"desc": "协变类型参数（生产者）。", "syntax": "class C<out T>", "example": "interface Producer<out T>"},
        "in": {"desc": "逆变类型参数（消费者）。", "syntax": "class C<in T>", "example": "interface Consumer<in T>"},
        "where": {"desc": "多个泛型约束。", "syntax": "where T : A, T : B", "example": "fun <T> f(x: T) where T : Comparable<T>"},
        "field": {"desc": "属性幕后字段（setter 中）。", "syntax": "field", "example": "set(value) { field = value }"},
        "get": {"desc": "属性 getter。", "syntax": "get() = ...", "example": "val size get() = list.size"},
        "set": {"desc": "属性 setter。", "syntax": "set(value) { ... }", "example": "var x = 0 set(v) { field = v }"},
        "value": {"desc": "setter 隐式参数名。", "syntax": "value", "example": "set(value) { field = value }"},
        "const": {"desc": "编译期常量（需在 object/companion 中）。", "syntax": "const val NAME = value", "example": "const val MAX = 100"},
        "inner": {"desc": "内部类（持有外部类引用）。", "syntax": "inner class Name", "example": "inner class Helper"},
        "enum": {"desc": "枚举类。", "syntax": "enum class Name { ... }", "example": "enum class Direction { NORTH, SOUTH }"},
    },
}


def keyword_detail(lang_key: str, word: str) -> dict:
    """获取某语言某关键字的详解，优先语言特有，回退通用库。"""
    extra = _LANG_KEYWORD_EXTRA.get(lang_key, {})
    if word in extra:
        return {"word": word, **extra[word]}
    if word in _COMMON_KEYWORDS:
        return {"word": word, **_COMMON_KEYWORDS[word]}
    # 回退：生成基本介绍
    return {
        "word": word,
        "desc": f"{lang_key} 语言中的关键字/保留字「{word}」，用于特定语法结构。",
        "syntax": word,
        "example": f"// {word} 用法示例",
    }


# ============================================================
# 二、标准库模块用法：每种语言至少 5 个模块完整用法
# 格式：{lang: [{name, desc, functions, example, tips}]}
# ============================================================

LANG_MODULES = {
    "python": [
        {
            "name": "os — 操作系统接口",
            "desc": "提供与操作系统交互的功能，包括文件/目录操作、环境变量、进程管理、路径处理等。",
            "functions": [
                "os.getcwd() — 获取当前工作目录",
                "os.chdir(path) — 切换工作目录",
                "os.listdir(path='.') — 列出目录内容",
                "os.makedirs(path, exist_ok=True) — 递归创建目录",
                "os.remove(path) / os.rmdir(path) — 删除文件/空目录",
                "os.rename(src, dst) — 重命名文件",
                "os.environ — 环境变量字典",
                "os.getenv(key, default) — 获取环境变量",
                "os.system(cmd) — 执行系统命令",
                "os.path.join(a, b) — 拼接路径",
                "os.path.exists(path) — 判断路径是否存在",
                "os.path.isfile / isdir — 判断文件/目录",
                "os.path.getsize(path) — 获取文件大小",
                "os.walk(top) — 递归遍历目录树",
            ],
            "example": """import os

# 目录操作
os.makedirs('data/output', exist_ok=True)
print('当前目录:', os.getcwd())

# 遍历目录
for root, dirs, files in os.walk('data'):
    for f in files:
        full = os.path.join(root, f)
        print(full, os.path.getsize(full), 'bytes')

# 环境变量
home = os.getenv('HOME', '/default')
os.environ['MY_VAR'] = 'hello'""",
            "tips": "路径拼接始终用 os.path.join，不要手动拼字符串；删除文件用 os.remove，删除目录树用 shutil.rmtree；os.system 只返回退出码，需要输出时用 subprocess。",
        },
        {
            "name": "sys — 系统相关参数和函数",
            "desc": "提供与 Python 解释器交互的功能，包括命令行参数、标准流、模块搜索路径、退出程序等。",
            "functions": [
                "sys.argv — 命令行参数列表（argv[0] 是脚本名）",
                "sys.exit(code) — 退出程序，0 表示成功",
                "sys.path — 模块搜索路径列表，可 append 添加",
                "sys.modules — 已导入模块字典",
                "sys.stdin / sys.stdout / sys.stderr — 标准输入/输出/错误流",
                "sys.platform — 平台标识（win32/darwin/linux）",
                "sys.version — Python 版本字符串",
                "sys.version_info — 版本命名元组",
                "sys.getsizeof(obj) — 获取对象占用字节数",
                "sys.setrecursionlimit(n) — 设置递归深度上限",
                "sys.exc_info() — 获取当前异常信息",
            ],
            "example": """import sys

# 命令行参数
if len(sys.argv) < 2:
    print('用法: python script.py <name>', file=sys.stderr)
    sys.exit(1)

name = sys.argv[1]
print(f'Hello, {name}!')

# 添加模块路径
sys.path.append('/path/to/my/modules')

# 平台判断
if sys.platform.startswith('win'):
    print('Windows 系统')
elif sys.platform == 'darwin':
    print('macOS')
else:
    print('Linux/Unix')""",
            "tips": "sys.exit(0) 是正常退出，非零表示错误；修改 sys.path 只在当前进程有效；递归深度默认 1000，大量递归需 setrecursionlimit；生产环境用 logging 替代 print 到 stderr。",
        },
        {
            "name": "json — JSON 编解码",
            "desc": "实现 JSON 数据的编码（序列化）和解码（反序列化），支持 Python 原生类型与 JSON 格式互转。",
            "functions": [
                "json.dumps(obj, indent=2, ensure_ascii=False) — 对象转 JSON 字符串",
                "json.dump(obj, fp) — 对象写入文件",
                "json.loads(s) — JSON 字符串转对象",
                "json.load(fp) — 从文件读取转对象",
                "json.JSONEncoder — 自定义编码器基类",
                "json.JSONDecoder — 自定义解码器",
                "default 参数 — 处理不可序列化对象的函数",
                "object_hook 参数 — 解码时自定义对象转换",
            ],
            "example": """import json
from datetime import datetime

# 编码
data = {
    'name': '张三',
    'age': 25,
    'skills': ['Python', 'JavaScript'],
    'active': True,
}
json_str = json.dumps(data, indent=2, ensure_ascii=False)
print(json_str)

# 解码
parsed = json.loads(json_str)
print(parsed['name'])  # 张三

# 写入/读取文件
with open('data.json', 'w', encoding='utf-8') as f:
    json.dump(data, f, ensure_ascii=False, indent=2)

with open('data.json', 'r', encoding='utf-8') as f:
    loaded = json.load(f)

# 处理 datetime（自定义 default）
def default(obj):
    if isinstance(obj, datetime):
        return obj.isoformat()
    raise TypeError(f'不可序列化: {type(obj)}')

json.dumps({'time': datetime.now()}, default=default)""",
            "tips": "中文必须 ensure_ascii=False 否则变成 \\uXXXX；datetime/set 等类型需自定义 default；大文件用 json.load 一次性读入内存，超大文件用 ijson 流式解析；JSON 不支持注释和尾逗号。",
        },
        {
            "name": "re — 正则表达式",
            "desc": "提供 Perl 风格的正则表达式匹配操作，支持搜索、替换、分割、匹配组提取等功能。",
            "functions": [
                "re.search(pattern, string) — 搜索第一个匹配，返回 Match 对象",
                "re.match(pattern, string) — 从字符串开头匹配",
                "re.fullmatch(pattern, string) — 整个字符串完全匹配",
                "re.findall(pattern, string) — 返回所有匹配的列表",
                "re.finditer(pattern, string) — 返回匹配迭代器",
                "re.sub(pattern, repl, string, count=0) — 替换匹配",
                "re.split(pattern, string, maxsplit=0) — 按匹配分割",
                "re.compile(pattern, flags) — 预编译正则，提高性能",
                "Match.group() / groups() / groupdict() — 获取匹配内容",
                "Match.start() / end() / span() — 获取匹配位置",
            ],
            "example": """import re

# 搜索匹配
text = '联系电话: 138-1234-5678, 邮箱: test@example.com'
phone = re.search(r'1[3-9]\\d-\\d{4}-\\d{4}', text)
if phone:
    print('找到电话:', phone.group())

# 提取所有邮箱
emails = re.findall(r'[\\w.-]+@[\\w.-]+\\.\\w+', text)
print('邮箱列表:', emails)

# 替换
masked = re.sub(r'(\\d{3})-\\d{4}-(\\d{4})', r'\\1-****-\\2', text)
print(masked)

# 分割
parts = re.split(r'[,，;；]', 'a,b，c;d；e')
print(parts)  # ['a', 'b', 'c', 'd', 'e']

# 命名分组 + 预编译
pattern = re.compile(r'(?P<year>\\d{4})-(?P<month>\\d{2})-(?P<day>\\d{2})')
m = pattern.search('日期: 2024-03-15')
if m:
    print(m.groupdict())  # {'year': '2024', 'month': '03', 'day': '15'}

# 常用标志
# re.IGNORECASE (re.I) — 忽略大小写
# re.MULTILINE (re.M) — 多行模式，^$ 匹配每行
# re.DOTALL (re.S) — . 匹配换行符
# re.VERBOSE (re.X) — 允许注释和空白""",
            "tips": "Python 字符串中反斜杠需转义，建议用原始字符串 r'...'；多次使用同一正则务必 compile 预编译；re.match 只匹配开头，需要任意位置用 re.search；替换中的反向引用用 \\1 或 \\g<name>；贪婪匹配 .* 后加 ? 变非贪婪 .*?。",
        },
        {
            "name": "datetime — 日期和时间处理",
            "desc": "提供日期、时间、时间间隔、时区等处理功能，支持日期运算、格式化解析、时间戳转换等。",
            "functions": [
                "datetime.datetime.now() — 当前本地时间",
                "datetime.datetime.utcnow() — 当前 UTC 时间",
                "datetime.date.today() — 今天日期",
                "datetime.timedelta(days, hours, minutes, seconds) — 时间间隔",
                "dt.strftime(format) — 日期格式化为字符串",
                "datetime.datetime.strptime(s, format) — 字符串解析为日期",
                "dt.timestamp() — 转为 Unix 时间戳",
                "datetime.datetime.fromtimestamp(ts) — 时间戳转日期",
                "dt.year / month / day / hour / minute / second — 属性访问",
                "dt.replace(year=..., month=...) — 替换字段生成新对象",
                "dt.weekday() — 星期几（0=周一）",
                "dt.isoformat() — ISO 8601 格式字符串",
            ],
            "example": """from datetime import datetime, date, timedelta

# 当前时间
now = datetime.now()
print(now.strftime('%Y-%m-%d %H:%M:%S'))

# 日期运算
today = date.today()
tomorrow = today + timedelta(days=1)
last_week = today - timedelta(weeks=1)
print('明天:', tomorrow, '上周:', last_week)

# 字符串解析
dt = datetime.strptime('2024-03-15 14:30:00', '%Y-%m-%d %H:%M:%S')
print(dt.year, dt.month, dt.day)

# 时间戳转换
ts = now.timestamp()
dt2 = datetime.fromtimestamp(ts)

# 计算两个日期差
d1 = date(2024, 1, 1)
d2 = date(2024, 12, 31)
diff = (d2 - d1).days
print(f'相差 {diff} 天')

# 常用格式符
# %Y 四位年 %y 两位年 %m 月 %d 日
# %H 24小时 %I 12小时 %M 分 %S 秒
# %A 星期全名 %a 星期缩写 %B 月全名 %b 月缩写
# %w 星期数字(0=周日) %j 年内第几天 %z 时区偏移""",
            "tips": "datetime 对象是不可变的，修改用 replace() 返回新对象；strptime 的格式符必须与字符串完全匹配；处理时区用 zoneinfo（Python 3.9+）或 pytz；日期比较直接用 < > ==；timedelta 只支持天/秒/微秒级，月/年运算用 dateutil.relativedelta。",
        },
    ],
    "javascript": [
        {
            "name": "Array — 数组方法",
            "desc": "JavaScript 数组内置方法极其丰富，涵盖遍历、映射、过滤、归约、查找、排序、增删等操作，是日常开发最常用的数据结构。",
            "functions": [
                "arr.map(fn) — 映射，返回新数组，每个元素经 fn 转换",
                "arr.filter(fn) — 过滤，返回满足条件的元素新数组",
                "arr.reduce(fn, init) — 归约，累计为单个值",
                "arr.forEach(fn) — 遍历，无返回值",
                "arr.find(fn) — 查找第一个满足条件的元素",
                "arr.findIndex(fn) — 查找第一个满足条件的索引",
                "arr.includes(val) — 判断是否包含某值",
                "arr.indexOf(val) — 首次出现的索引",
                "arr.some(fn) — 是否至少一个满足",
                "arr.every(fn) — 是否全部满足",
                "arr.sort(fn) — 排序（修改原数组）",
                "arr.reverse() — 反转（修改原数组）",
                "arr.push(val) / pop() — 末尾增/删",
                "arr.unshift(val) / shift() — 开头增/删",
                "arr.slice(start, end) — 截取子数组（不修改原数组）",
                "arr.splice(start, count, ...items) — 删除/插入（修改原数组）",
                "arr.concat(other) — 合并数组",
                "arr.join(separator) — 连接为字符串",
                "arr.flat(depth) — 扁平化嵌套数组",
                "arr.flatMap(fn) — map + flat 组合",
                "Array.from(iterable) — 类数组/可迭代对象转数组",
                "Array.isArray(val) — 判断是否为数组",
                "...arr — 展开运算符",
            ],
            "example": """// map 映射
const nums = [1, 2, 3, 4, 5];
const doubled = nums.map(n => n * 2);
console.log(doubled); // [2, 4, 6, 8, 10]

// filter 过滤
const evens = nums.filter(n => n % 2 === 0);
console.log(evens); // [2, 4]

// reduce 归约
const sum = nums.reduce((acc, n) => acc + n, 0);
console.log(sum); // 15

// 链式调用
const result = nums
  .filter(n => n > 2)
  .map(n => n * 10)
  .reduce((a, b) => a + b, 0);
console.log(result); // 120 (30+40+50)

// find 查找
const users = [{id:1,name:'Alice'}, {id:2,name:'Bob'}];
const user = users.find(u => u.id === 2);
console.log(user.name); // Bob

// sort 排序（注意默认按字符串排序）
const arr = [3, 1, 10, 2];
arr.sort((a, b) => a - b); // 数字升序
console.log(arr); // [1, 2, 3, 10]

// 解构 + 展开
const [first, ...rest] = nums;
const merged = [...nums, ...[6, 7, 8]];

// flat 扁平化
const nested = [1, [2, 3], [4, [5, 6]]];
console.log(nested.flat(2)); // [1, 2, 3, 4, 5, 6]""",
            "tips": "map/filter/reduce 不修改原数组，返回新数组；sort/reverse/splice/push/pop 会修改原数组，需要不可变时先 [...arr] 复制；sort 默认按 Unicode 码点排序，数字必须传比较函数 (a,b)=>a-b；reduce 的初始值建议始终提供，空数组否则报错；链式调用中每个方法返回新数组，不会影响原始数据。",
        },
        {
            "name": "Promise / async-await — 异步编程",
            "desc": "Promise 是 JavaScript 异步编程的核心，代表一个异步操作的最终完成或失败；async/await 是基于 Promise 的语法糖，让异步代码看起来像同步代码。",
            "functions": [
                "new Promise((resolve, reject) => { ... }) — 创建 Promise",
                "promise.then(onFulfilled, onRejected) — 成功/失败回调",
                "promise.catch(onRejected) — 捕获错误",
                "promise.finally(onFinally) — 无论成功失败都执行",
                "Promise.resolve(value) — 创建已成功的 Promise",
                "Promise.reject(reason) — 创建已失败的 Promise",
                "Promise.all([p1, p2]) — 全部成功才成功，返回结果数组",
                "Promise.allSettled([...]) — 全部完成后返回每个的状态",
                "Promise.race([...]) — 第一个完成的决定结果",
                "Promise.any([...]) — 第一个成功的决定结果",
                "async function name() { ... } — 声明异步函数",
                "await promise — 等待 Promise 完成并获取结果",
                "try { await ... } catch(e) { ... } — 异步错误处理",
            ],
            "example": """// 创建 Promise
function fetchData(url) {
  return new Promise((resolve, reject) => {
    setTimeout(() => {
      if (url) resolve({ data: 'from ' + url });
      else reject(new Error('url 为空'));
    }, 1000);
  });
}

// then/catch 链式
fetchData('/api/user')
  .then(res => {
    console.log(res.data);
    return fetchData('/api/posts');
  })
  .then(res => console.log(res.data))
  .catch(err => console.error('错误:', err.message))
  .finally(() => console.log('请求完成'));

// async/await 写法
async function loadAll() {
  try {
    const user = await fetchData('/api/user');
    const posts = await fetchData('/api/posts');
    console.log(user, posts);
  } catch (err) {
    console.error('加载失败:', err.message);
  }
}

// 并行执行（比串行快）
async function loadParallel() {
  const [user, posts] = await Promise.all([
    fetchData('/api/user'),
    fetchData('/api/posts'),
  ]);
  return { user, posts };
}

// 错误处理：allSettled 不中断
async function safeLoad() {
  const results = await Promise.allSettled([
    fetchData('/a'),
    fetchData(''), // 这个会失败
  ]);
  results.forEach(r => {
    if (r.status === 'fulfilled') console.log('成功:', r.value);
    else console.log('失败:', r.reason.message);
  });
}

// 超时控制
function withTimeout(promise, ms) {
  return Promise.race([
    promise,
    new Promise((_, reject) =>
      setTimeout(() => reject(new Error('超时')), ms)
    ),
  ]);
}""",
            "tips": "async 函数总是返回 Promise；await 只能在 async 函数内使用（顶层 await 在 ES2022 模块中可用）；多个独立异步操作用 Promise.all 并行，不要逐个 await（慢）；Promise.all 中任一失败则整体失败，需要部分失败容忍用 allSettled；catch 能捕获 then 链中所有错误，包括前一个 then 抛出的；避免在 forEach 中用 await（不会等待），用 for...of 或 Promise.all。",
        },
        {
            "name": "fetch / XMLHttpRequest — 网络请求",
            "desc": "fetch 是现代浏览器内置的 HTTP 请求 API，基于 Promise；XMLHttpRequest 是传统 API，支持进度事件和更底层控制。",
            "functions": [
                "fetch(url, options) — 发起请求，返回 Promise<Response>",
                "response.json() — 解析 JSON 响应体",
                "response.text() — 解析文本响应体",
                "response.blob() — 解析为 Blob（二进制）",
                "response.formData() — 解析为 FormData",
                "response.status / statusText / ok / headers — 响应信息",
                "options.method — GET/POST/PUT/DELETE/PATCH",
                "options.headers — 请求头对象",
                "options.body — 请求体（JSON.stringify / FormData）",
                "options.credentials — include/same-origin/omit",
                "options.signal — AbortController 信号用于取消",
                "new XMLHttpRequest() — 创建 XHR 对象",
                "xhr.open(method, url, async) — 初始化请求",
                "xhr.send(body) — 发送请求",
                "xhr.onload / onerror / onprogress — 事件回调",
                "xhr.response / responseText / status — 响应",
            ],
            "example": """// GET 请求
async function getUser(id) {
  const res = await fetch(`/api/users/${id}`);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

// POST 请求（JSON）
async function createUser(data) {
  const res = await fetch('/api/users', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  });
  return res.json();
}

// 上传文件（FormData）
async function uploadFile(file) {
  const formData = new FormData();
  formData.append('file', file);
  formData.append('description', 'my file');

  const res = await fetch('/api/upload', {
    method: 'POST',
    body: formData, // 不要手动设 Content-Type，浏览器自动加 boundary
  });
  return res.json();
}

// 取消请求（AbortController）
const controller = new AbortController();
fetch('/api/large-data', { signal: controller.signal })
  .then(res => res.json())
  .catch(err => {
    if (err.name === 'AbortError') console.log('请求已取消');
  });
// 5 秒后取消
setTimeout(() => controller.abort(), 5000);

// 带超时的 fetch 封装
async function fetchWithTimeout(url, options = {}, timeout = 8000) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeout);
  try {
    const res = await fetch(url, { ...options, signal: controller.signal });
    return res;
  } finally {
    clearTimeout(timer);
  }
}

// XMLHttpRequest（支持上传进度）
function uploadWithProgress(file, onProgress) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open('POST', '/api/upload');
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable) {
        onProgress(Math.round((e.loaded / e.total) * 100));
      }
    };
    xhr.onload = () => resolve(JSON.parse(xhr.responseText));
    xhr.onerror = () => reject(new Error('网络错误'));
    const fd = new FormData();
    fd.append('file', file);
    xhr.send(fd);
  });
}""",
            "tips": "fetch 只有网络错误才 reject，HTTP 4xx/5xx 不会 reject，需要手动检查 res.ok；JSON 请求体必须 JSON.stringify 并设 Content-Type；上传文件用 FormData 时不要手动设 Content-Type；跨域需要后端设置 CORS 头，credentials: include 时后端必须设 Access-Control-Allow-Credentials: true 且不能用通配符 origin；需要取消请求用 AbortController；旧浏览器不支持 fetch 时用 axios 或 XHR。",
        },
        {
            "name": "localStorage / sessionStorage — 浏览器存储",
            "desc": "Web Storage API 提供键值对存储，localStorage 持久保存（除非手动清除），sessionStorage 仅当前标签页会话有效，关闭标签页即清除。",
            "functions": [
                "localStorage.setItem(key, value) — 存储字符串值",
                "localStorage.getItem(key) — 读取值，不存在返回 null",
                "localStorage.removeItem(key) — 删除指定键",
                "localStorage.clear() — 清除所有数据",
                "localStorage.key(index) — 获取指定索引的键名",
                "localStorage.length — 存储的键数量",
                "sessionStorage — 同上方法，但仅会话有效",
                "JSON.stringify(obj) — 对象转字符串后存储",
                "JSON.parse(str) — 读取后解析为对象",
                "window.addEventListener('storage', fn) — 监听其他标签页的存储变化",
            ],
            "example": """// 基本存取
localStorage.setItem('username', '张三');
const name = localStorage.getItem('username');
console.log(name); // 张三

// 存储对象（必须 JSON 序列化）
const user = { id: 1, name: 'Alice', roles: ['admin', 'editor'] };
localStorage.setItem('user', JSON.stringify(user));

const saved = JSON.parse(localStorage.getItem('user'));
console.log(saved.name); // Alice

// 安全读取（防止 JSON 解析错误）
function getStorage(key, defaultValue = null) {
  try {
    const raw = localStorage.getItem(key);
    return raw ? JSON.parse(raw) : defaultValue;
  } catch (e) {
    console.warn(`读取 ${key} 失败:`, e);
    return defaultValue;
  }
}

function setStorage(key, value) {
  try {
    localStorage.setItem(key, JSON.stringify(value));
    return true;
  } catch (e) {
    console.warn(`写入 ${key} 失败（可能超出配额）:`, e);
    return false;
  }
}

// 删除与清除
localStorage.removeItem('tempData');
// localStorage.clear(); // 谨慎使用，清除全部

// sessionStorage（会话级）
sessionStorage.setItem('formDraft', JSON.stringify({ name: 'test' }));
// 关闭标签页后自动清除

// 监听其他标签页的存储变化（同源）
window.addEventListener('storage', (e) => {
  console.log(`键 ${e.key} 变化: ${e.oldValue} -> ${e.newValue}`);
  if (e.key === 'theme') {
    applyTheme(e.newValue);
  }
});

// 容量检测（通常 5-10MB）
function getStorageSize() {
  let total = 0;
  for (let key in localStorage) {
    if (localStorage.hasOwnProperty(key)) {
      total += localStorage.getItem(key).length + key.length;
    }
  }
  return (total / 1024).toFixed(2) + ' KB';
}""",
            "tips": "只能存储字符串，对象必须 JSON.stringify；存储容量约 5-10MB（因浏览器而异），超量抛 QuotaExceededError；localStorage 同源共享，不同协议/域名/端口隔离；storage 事件只在其他标签页触发，当前页不触发；敏感数据不要存 localStorage（XSS 可读取），用 httpOnly Cookie；大数据用 IndexedDB；隐私模式下部分浏览器禁用 localStorage，需 try-catch 保护。",
        },
        {
            "name": "Math / Number — 数学与数值处理",
            "desc": "Math 对象提供数学常量和函数；Number 对象提供数值解析、格式化、类型判断等功能，是数值计算的基础工具。",
            "functions": [
                "Math.abs(x) — 绝对值",
                "Math.ceil(x) — 向上取整",
                "Math.floor(x) — 向下取整",
                "Math.round(x) — 四舍五入",
                "Math.trunc(x) — 截断小数部分（ES6）",
                "Math.max(a, b, ...) / Math.min(...) — 最大/最小值",
                "Math.pow(base, exp) — 幂运算",
                "Math.sqrt(x) — 平方根",
                "Math.cbrt(x) — 立方根（ES6）",
                "Math.random() — 0 到 1 之间随机数",
                "Math.log(x) / log2 / log10 — 对数",
                "Math.sin / cos / tan — 三角函数（弧度）",
                "Math.PI / Math.E — 常量 π 和自然对数底",
                "Math.hypot(a, b) — 平方和的平方根（ES6）",
                "Number.parseInt(s, radix) — 解析整数",
                "Number.parseFloat(s) — 解析浮点数",
                "Number.isInteger(x) — 是否整数",
                "Number.isNaN(x) — 是否 NaN（比全局 isNaN 严格）",
                "Number.isFinite(x) — 是否有限数",
                "num.toFixed(digits) — 固定小数位（返回字符串）",
                "num.toPrecision(precision) — 有效数字",
                "num.toString(radix) — 转字符串（可指定进制）",
            ],
            "example": """// 取整
console.log(Math.ceil(4.1));   // 5
console.log(Math.floor(4.9));  // 4
console.log(Math.round(4.5));  // 5
console.log(Math.trunc(-4.9)); // -4（直接截断）

// 随机数
function randomInt(min, max) {
  return Math.floor(Math.random() * (max - min + 1)) + min;
}
console.log(randomInt(1, 100)); // 1-100 随机整数

function randomChoice(arr) {
  return arr[Math.floor(Math.random() * arr.length)];
}

// 最大最小值（展开运算符传数组）
const nums = [3, 7, 2, 9, 5];
console.log(Math.max(...nums)); // 9
console.log(Math.min(...nums)); // 2

// 数值解析
console.log(Number.parseInt('123abc'));     // 123
console.log(Number.parseInt('1010', 2));     // 10（二进制）
console.log(Number.parseFloat('3.14元'));    // 3.14
console.log(Number('123'));                   // 123

// 类型判断
console.log(Number.isInteger(42));    // true
console.log(Number.isInteger(42.5));  // false
console.log(Number.isNaN(NaN));       // true
console.log(Number.isNaN('abc'));     // false（全局 isNaN('abc') 是 true）
console.log(Number.isFinite(1 / 0));  // false

// 格式化
const price = 99.8;
console.log(price.toFixed(2));    // "99.80"
console.log(price.toPrecision(3)); // "99.8"
console.log((1234567).toString(16)); // "12d687"（十六进制）

// 常用计算
function clamp(val, min, max) {
  return Math.min(Math.max(val, min), max);
}

function lerp(a, b, t) { // 线性插值
  return a + (b - a) * t;
}

function distance(x1, y1, x2, y2) {
  return Math.hypot(x2 - x1, y2 - y1);
}

// 注意：浮点数精度问题
console.log(0.1 + 0.2); // 0.30000000000000004
// 解决：四舍五入或用整数运算
console.log(Math.round((0.1 + 0.2) * 100) / 100); // 0.3""",
            "tips": "Math.random() 不是加密安全的，安全场景用 crypto.getRandomValues()；浮点数运算有精度误差（0.1+0.2!==0.3），金额计算用整数（分）或 toFixed 后比较；Number.isNaN 比全局 isNaN 更严格（不会把非数字字符串当 NaN）；toFixed 返回字符串，需要数值再 Number()；parseInt 建议始终传第二个参数进制，避免 '08' 被当八进制；大整数（>2^53）用 BigInt。",
        },
    ],
}

# 为其余语言补充模块（C/C++/Java/Go/Rust/C#/Swift/Kotlin）
import json as _json

def _more_modules():
    return {
        "c": [
            {
                "name": "stdio.h — 标准输入输出",
                "desc": "C 语言标准输入输出库，提供文件操作、格式化输入输出、字符读写等功能，是 C 程序最基础的库。",
                "functions": [
                    "printf(format, ...) — 格式化输出到 stdout",
                    "scanf(format, ...) — 从 stdin 格式化输入",
                    "fprintf(fp, format, ...) — 格式化输出到文件",
                    "fscanf(fp, format, ...) — 从文件格式化输入",
                    "sprintf(buf, format, ...) — 格式化输出到字符串缓冲区",
                    "sscanf(str, format, ...) — 从字符串格式化输入",
                    "fopen(path, mode) — 打开文件，返回 FILE*",
                    "fclose(fp) — 关闭文件",
                    "fread(buf, size, count, fp) — 从文件读取",
                    "fwrite(buf, size, count, fp) — 写入文件",
                    "fgets(buf, size, fp) — 读取一行",
                    "fputs(str, fp) — 写入字符串",
                    "getchar() / putchar(c) — 读写单个字符",
                    "feof(fp) / ferror(fp) — 判断文件结束/错误",
                    "fseek(fp, offset, whence) — 移动文件指针",
                    "ftell(fp) — 获取当前文件位置",
                    "rewind(fp) — 回到文件开头",
                    "fflush(fp) — 刷新缓冲区",
                    "perror(msg) — 打印错误信息",
                ],
                "example": """#include <stdio.h>
#include <stdlib.h>

int main() {
    // 格式化输出
    printf("整数: %d, 浮点数: %.2f, 字符串: %s\\n", 42, 3.14, "hello");

    // 格式化输入
    int age;
    char name[50];
    printf("输入姓名和年龄: ");
    scanf("%s %d", name, &age);
    printf("%s, %d 岁\\n", name, age);

    // 文件写入
    FILE *fp = fopen("data.txt", "w");
    if (!fp) { perror("打开失败"); return 1; }
    fprintf(fp, "第一行\\n第二行\\n数字: %d\\n", 100);
    fclose(fp);

    // 文件读取
    fp = fopen("data.txt", "r");
    if (!fp) { perror("打开失败"); return 1; }
    char line[256];
    while (fgets(line, sizeof(line), fp)) {
        printf("%s", line);
    }
    fclose(fp);

    // sprintf 拼接字符串
    char buf[100];
    sprintf(buf, "ID=%04d, Score=%.1f", 7, 95.5);
    printf("%s\\n", buf);

    // 二进制文件读写
    int data[] = {1, 2, 3, 4, 5};
    fp = fopen("binary.dat", "wb");
    fwrite(data, sizeof(int), 5, fp);
    fclose(fp);

    int read_data[5];
    fp = fopen("binary.dat", "rb");
    fread(read_data, sizeof(int), 5, fp);
    fclose(fp);

    return 0;
}""",
                "tips": "fopen 模式：r 读 w 写（清空）a 追加 r+ 读写 w+ 读写（清空），加 b 为二进制；scanf 的变量必须传地址 &；fgets 会保留换行符；文件操作必须检查 fopen 返回值；sprintf 有缓冲区溢出风险，用 snprintf 更安全；printf 格式符：%d 整数 %f 浮点 %s 字符串 %c 字符 %x 十六进制 %p 指针 %% 百分号。",
            },
            {
                "name": "stdlib.h — 标准工具库",
                "desc": "提供内存分配、程序控制、数值转换、随机数、排序查找等通用工具函数，是 C 标准库的核心组成部分。",
                "functions": [
                    "malloc(size) — 分配内存（未初始化）",
                    "calloc(count, size) — 分配并初始化为 0",
                    "realloc(ptr, size) — 重新分配内存大小",
                    "free(ptr) — 释放内存",
                    "exit(status) — 退出程序",
                    "abort() — 异常终止程序",
                    "atexit(func) — 注册退出时执行的函数",
                    "system(cmd) — 执行系统命令",
                    "getenv(name) — 获取环境变量",
                    "atoi(str) — 字符串转整数",
                    "atof(str) — 字符串转浮点数",
                    "atol(str) — 字符串转长整数",
                    "strtol(str, &endptr, base) — 字符串转长整数（可检测错误）",
                    "rand() — 生成伪随机数",
                    "srand(seed) — 设置随机数种子",
                    "qsort(base, count, size, compar) — 快速排序",
                    "bsearch(key, base, count, size, compar) — 二分查找",
                    "abs(x) — 整数绝对值",
                    "div(num, denom) — 整数除法返回商和余数",
                    "EXIT_SUCCESS / EXIT_FAILURE — 退出状态常量",
                ],
                "example": """#include <stdio.h>
#include <stdlib.h>
#include <time.h>

// 比较函数（qsort/bsearch 用）
int compare_int(const void *a, const void *b) {
    return (*(int*)a - *(int*)b);
}

int main() {
    // 动态内存分配
    int *arr = (int*)malloc(10 * sizeof(int));
    if (!arr) { fprintf(stderr, "内存分配失败\\n"); return 1; }

    for (int i = 0; i < 10; i++) arr[i] = i * i;
    for (int i = 0; i < 10; i++) printf("%d ", arr[i]);
    printf("\\n");

    // 重新分配（扩容）
    arr = (int*)realloc(arr, 20 * sizeof(int));
    for (int i = 10; i < 20; i++) arr[i] = i;
    free(arr); // 释放内存

    // calloc 自动初始化为 0
    int *zeroed = (int*)calloc(5, sizeof(int));
    printf("%d %d %d\\n", zeroed[0], zeroed[1], zeroed[2]); // 0 0 0
    free(zeroed);

    // 字符串转数值
    printf("%d\\n", atoi("123"));       // 123
    printf("%.2f\\n", atof("3.14"));    // 3.14

    // strtol 更安全（可检测非法字符）
    char *end;
    long val = strtol("123abc", &end, 10);
    printf("值: %ld, 剩余: %s\\n", val, end); // 123, abc

    // 随机数
    srand((unsigned)time(NULL)); // 用时间做种子
    for (int i = 0; i < 5; i++) {
        printf("%d ", rand() % 100 + 1); // 1-100
    }
    printf("\\n");

    // qsort 排序
    int data[] = {5, 2, 8, 1, 9, 3};
    int n = sizeof(data) / sizeof(data[0]);
    qsort(data, n, sizeof(int), compare_int);
    for (int i = 0; i < n; i++) printf("%d ", data[i]);
    printf("\\n"); // 1 2 3 5 8 9

    // bsearch 二分查找（数组必须已排序）
    int key = 5;
    int *found = (int*)bsearch(&key, data, n, sizeof(int), compare_int);
    if (found) printf("找到 %d\\n", *found);

    // 环境变量
    char *path = getenv("PATH");
    if (path) printf("PATH: %.50s...\\n", path);

    return EXIT_SUCCESS;
}""",
                "tips": "malloc 分配的内存未初始化，值是随机的，需要用 calloc 或手动 memset；free 后指针变成野指针，建议置为 NULL；realloc 可能返回新地址，必须用返回值重新赋值，不要直接 free 旧指针；qsort 的比较函数返回 <0/=0/>0，注意整数相减可能溢出；rand() 的范围是 0 到 RAND_MAX（至少 32767），取模用 rand()%(max-min+1)+min；内存泄漏用 valgrind 检测。",
            },
            {
                "name": "string.h — 字符串处理",
                "desc": "提供字符串复制、拼接、比较、查找、长度计算等函数，以及内存块操作函数，是 C 语言字符串处理的核心库。",
                "functions": [
                    "strlen(s) — 字符串长度（不含 \\\\0）",
                    "strcpy(dest, src) — 复制字符串",
                    "strncpy(dest, src, n) — 最多复制 n 个字符",
                    "strcat(dest, src) — 拼接字符串",
                    "strncat(dest, src, n) — 最多拼接 n 个字符",
                    "strcmp(s1, s2) — 比较字符串",
                    "strncmp(s1, s2, n) — 比较前 n 个字符",
                    "strchr(s, c) — 查找字符首次出现",
                    "strrchr(s, c) — 查找字符末次出现",
                    "strstr(haystack, needle) — 查找子串",
                    "strtok(str, delim) — 分割字符串（破坏性）",
                    "strdup(s) — 复制字符串到新分配内存（POSIX）",
                    "memcpy(dest, src, n) — 复制 n 字节内存",
                    "memmove(dest, src, n) — 移动内存（支持重叠）",
                    "memcmp(s1, s2, n) — 比较 n 字节内存",
                    "memset(s, c, n) — 设置 n 字节为 c",
                    "memchr(s, c, n) — 在 n 字节内查找字符",
                ],
                "example": """#include <stdio.h>
#include <string.h>

int main() {
    // 长度
    char s[] = "Hello, World!";
    printf("长度: %zu\\n", strlen(s)); // 13

    // 复制
    char dest[50];
    strcpy(dest, s);
    printf("复制: %s\\n", dest);
    strncpy(dest, "Hi", 2); // 只复制2个字符
    dest[2] = '\\\\0'; // 手动加结束符

    // 拼接
    strcpy(dest, "Hello");
    strcat(dest, ", ");
    strcat(dest, "World!");
    printf("拼接: %s\\n", dest); // Hello, World!

    // 比较
    printf("比较: %d\\n", strcmp("abc", "abc"));  // 0 相等
    printf("比较: %d\\n", strcmp("abc", "abd"));  // <0
    printf("比较: %d\\n", strncmp("abc123", "abc456", 3)); // 0 前3个相同

    // 查找字符
    char *p = strchr("hello@world.com", '@');
    if (p) printf("找到 @ 在位置: %ld\\n", p - "hello@world.com");
    char *last = strrchr("a/b/c/d", '/');
    printf("最后一个 / 后: %s\\n", last + 1); // d

    // 查找子串
    char *sub = strstr("Hello, World!", "World");
    if (sub) printf("找到子串: %s\\n", sub); // World!

    // 分割字符串（注意：strtok 会修改原字符串，且不可重入）
    char csv[] = "apple,banana,orange,grape";
    char *token = strtok(csv, ",");
    while (token) {
        printf("  %s\\n", token);
        token = strtok(NULL, ","); // 后续调用传 NULL
    }

    // 内存操作
    int src[5] = {1, 2, 3, 4, 5};
    int dst[5];
    memcpy(dst, src, sizeof(src)); // 复制数组
    memset(dst, 0, sizeof(dst));   // 清零
    memmove(&src[1], src, 4 * sizeof(int)); // 重叠区域移动

    // memset 常用于结构体清零
    struct { int x; char name[20]; } obj;
    memset(&obj, 0, sizeof(obj));

    return 0;
}""",
                "tips": "所有 str 函数都依赖 \\\\0 结束符，缓冲区必须足够大；strcpy/strcat 不检查缓冲区大小，容易溢出，用 strncpy/strncat 更安全；strncpy 不会自动加 \\\\0，需要手动补；strcmp 返回 <0/=0/>0，不要假设是 -1/0/1；strtok 不可重入且会修改原字符串，多线程或嵌套分割用 strtok_r（POSIX）或自己写分割；memcpy 不支持重叠区域，重叠用 memmove；strlen 返回 size_t（无符号），比较时注意类型。",
            },
            {
                "name": "math.h — 数学函数库",
                "desc": "提供三角函数、指数对数、幂运算、取整、绝对值等数学函数，编译时通常需要链接数学库 -lm。",
                "functions": [
                    "sin(x) / cos(x) / tan(x) — 三角函数（弧度）",
                    "asin(x) / acos(x) / atan(x) — 反三角函数",
                    "atan2(y, x) — 两点夹角（更安全）",
                    "sinh / cosh / tanh — 双曲函数",
                    "exp(x) — e 的 x 次方",
                    "log(x) — 自然对数（ln）",
                    "log10(x) — 常用对数（lg）",
                    "log2(x) — 以 2 为底的对数（C99）",
                    "pow(base, exp) — 幂运算",
                    "sqrt(x) — 平方根",
                    "cbrt(x) — 立方根（C99）",
                    "hypot(x, y) — 平方和平方根（C99）",
                    "ceil(x) — 向上取整",
                    "floor(x) — 向下取整",
                    "round(x) — 四舍五入（C99）",
                    "trunc(x) — 截断小数（C99）",
                    "fabs(x) — 浮点数绝对值",
                    "abs(x) — 整数绝对值（stdlib.h）",
                    "fmod(x, y) — 浮点数取模",
                    "fmin(x, y) / fmax(x, y) — 最小/最大值（C99）",
                    "M_PI / M_E — π 和 e 常量（需定义 _USE_MATH_DEFINES）",
                    "isfinite / isnan / isinf — 数值状态判断（C99）",
                ],
                "example": """#include <stdio.h>
#define _USE_MATH_DEFINES // 在 include math.h 前定义
#include <math.h>

int main() {
    // 三角函数（弧度）
    double angle = M_PI / 4; // 45度
    printf("sin(45°)=%.4f\\n", sin(angle));  // 0.7071
    printf("cos(45°)=%.4f\\n", cos(angle));  // 0.7071
    printf("tan(45°)=%.4f\\n", tan(angle));  // 1.0000

    // 角度转弧度
    double deg = 30;
    double rad = deg * M_PI / 180.0;
    printf("sin(30°)=%.2f\\n", sin(rad)); // 0.50

    // 指数对数
    printf("e^2=%.4f\\n", exp(2));       // 7.3891
    printf("ln(10)=%.4f\\n", log(10));    // 2.3026
    printf("log10(1000)=%.1f\\n", log10(1000)); // 3.0
    printf("2^10=%.0f\\n", pow(2, 10));   // 1024

    // 幂与根
    printf("sqrt(144)=%.0f\\n", sqrt(144)); // 12
    printf("cbrt(27)=%.0f\\n", cbrt(27));   // 3
    printf("hypot(3,4)=%.0f\\n", hypot(3, 4)); // 5（勾股定理）

    // 取整
    printf("ceil(4.1)=%.0f\\n", ceil(4.1));   // 5
    printf("floor(4.9)=%.0f\\n", floor(4.9)); // 4
    printf("round(4.5)=%.0f\\n", round(4.5)); // 5
    printf("trunc(-4.9)=%.0f\\n", trunc(-4.9)); // -4

    // 绝对值与取模
    printf("fabs(-3.14)=%.2f\\n", fabs(-3.14)); // 3.14
    printf("fmod(10.5, 3.2)=%.2f\\n", fmod(10.5, 3.2)); // 0.90

    // 最小最大
    printf("fmin(3,7)=%.0f\\n", fmin(3, 7)); // 3
    printf("fmax(3,7)=%.0f\\n", fmax(3, 7)); // 7

    // 数值状态判断
    printf("isnan(0/0.0)=%d\\n", isnan(0.0/0.0));   // 1
    printf("isinf(1/0.0)=%d\\n", isinf(1.0/0.0));   // 1
    printf("isfinite(1.0)=%d\\n", isfinite(1.0));    // 1

    // 实际应用：两点距离
    double x1=1, y1=2, x2=4, y2=6;
    double dist = hypot(x2-x1, y2-y1);
    printf("两点距离: %.2f\\n", dist); // 5.00

    // 圆的面积
    double r = 5;
    printf("半径 %.0f 的圆面积: %.2f\\n", r, M_PI * r * r); // 78.54

    return 0;
}""",
                "tips": "三角函数参数是弧度不是角度，角度转弧度用 deg*M_PI/180；M_PI 等常量需要在 include math.h 前定义 _USE_MATH_DEFINES（Windows）或用 -lm 链接；sqrt 参数为负会返回 NaN；pow(0,0) 结果是 1 但数学上未定义；fmod 结果符号与被除数相同；编译时加 -lm 链接数学库（Linux）；NaN 不等于任何值包括自己，用 isnan 判断；浮点数比较不要直接用 ==，用 fabs(a-b) < epsilon。",
            },
            {
                "name": "time.h — 时间与日期处理",
                "desc": "提供系统时间获取、时间格式化、时间计算、计时等功能，支持 Unix 时间戳和分解时间结构之间的转换。",
                "functions": [
                    "time(NULL) — 获取当前 Unix 时间戳（秒）",
                    "ctime(&t) — 时间戳转可读字符串",
                    "localtime(&t) — 时间戳转本地时间 struct tm*",
                    "gmtime(&t) — 时间戳转 UTC 时间 struct tm*",
                    "mktime(&tm) — struct tm 转时间戳",
                    "asctime(&tm) — struct tm 转可读字符串",
                    "strftime(buf, size, format, &tm) — 格式化时间",
                    "strptime(str, format, &tm) — 字符串解析为时间（POSIX）",
                    "difftime(t2, t1) — 两个时间戳的差值（秒）",
                    "clock() — 程序占用的 CPU 时钟数",
                    "CLOCKS_PER_SEC — 每秒时钟数（用于 clock 换算）",
                    "struct tm 字段：tm_year(年-1900) tm_mon(月0-11) tm_mday(日1-31) tm_hour tm_min tm_sec tm_wday(星期0-6) tm_yday(年内第几天) tm_isdst(夏令时)",
                ],
                "example": """#include <stdio.h>
#include <time.h>

int main() {
    // 获取当前时间戳
    time_t now = time(NULL);
    printf("当前时间戳: %lld 秒\\n", (long long)now);

    // 简单可读格式
    printf("当前时间: %s", ctime(&now)); // 自带换行

    // 分解为本地时间
    struct tm *local = localtime(&now);
    printf("年: %d, 月: %d, 日: %d\\n",
           local->tm_year + 1900, local->tm_mon + 1, local->tm_mday);
    printf("时: %d, 分: %d, 秒: %d\\n",
           local->tm_hour, local->tm_min, local->tm_sec);
    printf("星期: %d (0=周日)\\n", local->tm_wday);

    // 格式化输出
    char buf[100];
    strftime(buf, sizeof(buf), "%Y-%m-%d %H:%M:%S", local);
    printf("格式化: %s\\n", buf); // 2024-03-15 14:30:00

    strftime(buf, sizeof(buf), "%Y年%m月%d日 %A", local);
    printf("中文格式: %s\\n", buf);

    // 常用格式符
    // %Y 四位年 %y 两位年 %m 月 %d 日
    // %H 24小时 %I 12小时 %M 分 %S 秒
    // %A 星期全名 %a 星期缩写 %B 月全名 %b 月缩写
    // %j 年内第几天 %w 星期数字 %Z 时区名 %% 百分号

    // 时间计算
    time_t t1 = time(NULL);
    // ... 做一些操作 ...
    time_t t2 = time(NULL);
    double elapsed = difftime(t2, t1);
    printf("经过 %.0f 秒\\n", elapsed);

    // 计算特定日期的时间戳
    struct tm target = {0};
    target.tm_year = 2024 - 1900;
    target.tm_mon = 12 - 1;
    target.tm_mday = 25;
    target.tm_hour = 0;
    target.tm_min = 0;
    target.tm_sec = 0;
    time_t christmas = mktime(&target);
    printf("圣诞节还有 %.0f 秒\\n", difftime(christmas, now));

    // CPU 计时（测量代码执行时间）
    clock_t start = clock();
    // 执行需要计时的代码
    volatile long sum = 0;
    for (long i = 0; i < 1000000; i++) sum += i;
    clock_t end = clock();
    double cpu_time = (double)(end - start) / CLOCKS_PER_SEC;
    printf("CPU 时间: %.4f 秒\\n", cpu_time);

    // UTC 时间
    struct tm *utc = gmtime(&now);
    strftime(buf, sizeof(buf), "%Y-%m-%d %H:%M:%S UTC", utc);
    printf("UTC: %s\\n", buf);

    return 0;
}""",
                "tips": "struct tm 的年份要加 1900，月份是 0-11 要加 1，星期 0 是周日；localtime 返回的指针指向静态内存，后续调用会覆盖，需要保存时用 memcpy 或 localtime_r；time() 返回的是秒级精度，毫秒级用 clock_gettime(CLOCK_MONOTONIC)（POSIX）或 GetSystemTime（Windows）；clock() 测量的是 CPU 时间不是墙钟时间，sleep 时间不计入；strftime 的 %A %B 受系统 locale 影响，中文需要 setlocale(LC_ALL, \"zh_CN.UTF-8\")；时间戳是 UTC 秒数，无时区概念，localtime 才涉及时区转换。",
            },
        ],
        "cpp": [
            {
                "name": "iostream — 输入输出流",
                "desc": "C++ 标准输入输出库，提供 cin/cout/cerr/clog 流对象和 << >> 运算符，支持格式化输出、文件流、字符串流等。",
                "functions": [
                    "cout << x — 输出到标准输出",
                    "cin >> x — 从标准输入读取",
                    "cerr << x — 输出到标准错误（无缓冲）",
                    "clog << x — 输出到标准错误（有缓冲）",
                    "endl — 输出换行并刷新缓冲区",
                    "ends — 输出空字符",
                    "flush — 刷新流缓冲区",
                    "setw(n) — 设置字段宽度（iomanip）",
                    "setfill(c) — 设置填充字符（iomanip）",
                    "setprecision(n) — 设置浮点数精度（iomanip）",
                    "fixed / scientific — 浮点数格式（iomanip）",
                    "left / right / internal — 对齐方式",
                    "hex / oct / dec — 进制输出",
                    "boolalpha / noboolalpha — bool 输出 true/false",
                    "showbase / noshowbase — 显示进制前缀",
                    "cin.get() / getline(cin, str) — 读取字符/行",
                    "cin.ignore() — 忽略输入缓冲区字符",
                    "ifstream / ofstream / fstream — 文件流",
                    "istringstream / ostringstream — 字符串流",
                ],
                "example": """#include <iostream>
#include <iomanip>
#include <fstream>
#include <sstream>
#include <string>

using namespace std;

int main() {
    // 基本输出
    cout << "Hello, World!" << endl;
    cout << "整数: " << 42 << ", 浮点数: " << 3.14 << endl;

    // 基本输入
    int age;
    string name;
    cout << "输入姓名和年龄: ";
    cin >> name >> age;
    cout << name << ", " << age << " 岁" << endl;

    // 读取整行（cin >> 遇到空格停止，getline 读整行）
    cin.ignore(); // 忽略之前的换行
    string line;
    cout << "输入一行: ";
    getline(cin, line);
    cout << "你输入了: " << line << endl;

    // 格式化输出
    double pi = 3.1415926535;
    cout << fixed << setprecision(2) << pi << endl; // 3.14
    cout << scientific << setprecision(4) << pi << endl; // 3.1416e+00

    // 字段宽度与填充
    cout << dec; // 恢复十进制
    cout << setw(10) << left << "姓名" << setw(6) << "年龄" << endl;
    cout << setw(10) << left << "张三" << setw(6) << 25 << endl;
    cout << setfill('0') << setw(8) << 42 << endl; // 00000042
    cout << setfill(' '); // 恢复

    // 进制输出
    cout << hex << showbase << 255 << endl; // 0xff
    cout << oct << showbase << 255 << endl; // 0377
    cout << dec << noshowbase; // 恢复

    // bool 输出
    cout << boolalpha << true << " " << false << endl; // true false
    cout << noboolalpha;

    // 文件输出
    ofstream out("data.txt");
    if (out.is_open()) {
        out << "第一行" << endl;
        out << "数字: " << 100 << endl;
        out.close();
    }

    // 文件输入
    ifstream in("data.txt");
    if (in.is_open()) {
        string content;
        while (getline(in, content)) {
            cout << content << endl;
        }
        in.close();
    }

    // 字符串流（类型转换）
    ostringstream oss;
    oss << "ID=" << 42 << ", Score=" << 95.5;
    string result = oss.str();
    cout << result << endl; // ID=42, Score=95.5

    istringstream iss("10 20 30");
    int a, b, c;
    iss >> a >> b >> c;
    cout << a + b + c << endl; // 60

    // 错误输出
    cerr << "这是错误信息" << endl;

    return 0;
}""",
                "tips": "endl 会刷新缓冲区，频繁输出用 '\\n' 性能更好；cin >> 读取后缓冲区会残留换行符，后续 getline 前需要 cin.ignore()；setw 只影响下一个输出，其他操纵符持续有效直到改变；ofstream 默认模式是截断写入，追加用 ios::app，二进制用 ios::binary；istringstream 做字符串转数值比 atoi 更安全（可检查失败）；cout 输出 double 默认 6 位有效数字，用 setprecision 配合 fixed 控制小数位；文件流对象离开作用域自动关闭，但显式 close 更清晰。",
            },
            {
                "name": "vector — 动态数组容器",
                "desc": "std::vector 是 C++ 最常用的顺序容器，封装了动态数组，支持自动扩容、随机访问、尾部高效增删，是 C++ 标准库容器的代表。",
                "functions": [
                    "vector<T> v — 创建空向量",
                    "vector<T> v(n) — 创建 n 个默认元素",
                    "vector<T> v(n, val) — 创建 n 个 val",
                    "vector<T> v{...} — 初始化列表",
                    "v.push_back(x) — 末尾添加元素",
                    "v.pop_back() — 末尾删除元素",
                    "v.insert(pos, x) — 在位置插入",
                    "v.erase(pos) — 删除位置元素",
                    "v.emplace_back(args) — 末尾原位构造（更高效）",
                    "v[i] / v.at(i) — 访问元素（at 有边界检查）",
                    "v.front() / v.back() — 首/尾元素",
                    "v.size() — 元素个数",
                    "v.capacity() — 当前容量",
                    "v.empty() — 是否为空",
                    "v.clear() — 清空所有元素",
                    "v.resize(n) — 改变大小",
                    "v.reserve(n) — 预留容量",
                    "v.shrink_to_fit() — 释放多余容量",
                    "v.begin() / v.end() — 首尾迭代器",
                    "v.rbegin() / v.rend() — 反向迭代器",
                    "v.data() — 获取底层数组指针",
                    "v.assign(n, val) — 重新赋值",
                    "v.swap(other) — 交换两个向量",
                    "范围 for: for (auto& x : v)",
                    "算法: sort(v.begin(), v.end()) / find / count / accumulate",
                ],
                "example": """#include <iostream>
#include <vector>
#include <algorithm>
#include <numeric>

using namespace std;

int main() {
    // 创建与初始化
    vector<int> v1;                    // 空
    vector<int> v2(5);                 // 5个0
    vector<int> v3(5, 10);             // 5个10
    vector<int> v4{1, 2, 3, 4, 5};    // 初始化列表

    // 末尾添加
    vector<int> v;
    v.push_back(10);
    v.push_back(20);
    v.emplace_back(30); // 原位构造，避免拷贝
    cout << "大小: " << v.size() << endl;     // 3
    cout << "容量: " << v.capacity() << endl; // 可能是4

    // 访问
    cout << v[0] << endl;      // 10（无边界检查）
    cout << v.at(1) << endl;   // 20（越界抛 out_of_range）
    cout << v.front() << endl;  // 10
    cout << v.back() << endl;   // 30

    // 遍历
    for (int i = 0; i < v.size(); i++) cout << v[i] << " ";
    cout << endl;
    for (int x : v) cout << x << " ";  // 范围 for（C++11）
    cout << endl;
    for (auto it = v.begin(); it != v.end(); ++it) cout << *it << " ";
    cout << endl;

    // 修改与删除
    v[0] = 100;
    v.pop_back(); // 删除末尾
    v.insert(v.begin() + 1, 15); // 在索引1插入
    v.erase(v.begin()); // 删除第一个
    for (int x : v) cout << x << " ";
    cout << endl;

    // 排序与查找
    vector<int> nums{5, 2, 8, 1, 9, 3};
    sort(nums.begin(), nums.end()); // 升序
    sort(nums.rbegin(), nums.rend()); // 降序
    sort(nums.begin(), nums.end(), greater<int>()); // 降序

    auto it = find(nums.begin(), nums.end(), 8);
    if (it != nums.end()) cout << "找到 8 在位置 " << (it - nums.begin()) << endl;

    int cnt = count(nums.begin(), nums.end(), 3);
    int sum = accumulate(nums.begin(), nums.end(), 0);
    cout << "3出现 " << cnt << " 次, 总和=" << sum << endl;

    // 自定义排序
    vector<pair<string, int>> people{{"Alice", 25}, {"Bob", 30}, {"Charlie", 20}};
    sort(people.begin(), people.end(), [](const auto& a, const auto& b) {
        return a.second < b.second; // 按年龄升序
    });

    // 二维向量
    vector<vector<int>> matrix(3, vector<int>(4, 0)); // 3行4列全0
    matrix[0][0] = 1;
    matrix[2][3] = 9;

    // 预留容量（避免多次扩容）
    vector<int> big;
    big.reserve(1000); // 预留1000容量
    for (int i = 0; i < 1000; i++) big.push_back(i);

    // 清空与释放
    v.clear(); // 清空元素，容量不变
    vector<int>().swap(v); // 释放内存（技巧）

    return 0;
}""",
                "tips": "vector 底层是连续数组，随机访问 O(1)，尾部增删 O(1) 摊还，中间插入删除 O(n)；push_back 扩容通常是 1.5x 或 2x，大量添加前用 reserve 避免多次扩容；[] 不检查边界，越界是未定义行为，调试用 at()；迭代器在插入/删除/扩容后可能失效，需要重新获取；vector<bool> 是特化版本，不存储 bool 而是位，行为特殊，避免使用；用 emplace_back 替代 push_back 可以避免临时对象拷贝；范围 for 中修改元素用引用 for (auto& x : v)，不需要修改用 const auto&。",
            },
            {
                "name": "string — 字符串类",
                "desc": "std::string 是 C++ 标准字符串类，封装了字符数组和常用字符串操作，支持动态长度、拼接、查找、替换、子串等，比 C 风格字符串更安全易用。",
                "functions": [
                    "string s — 空字符串",
                    "string s(\"hello\") — 从 C 字符串构造",
                    "string s(n, c) — n 个字符 c",
                    "s1 + s2 — 字符串拼接",
                    "s += x — 追加（字符串/字符/数字？数字需 to_string）",
                    "s.append(str) — 追加",
                    "s.size() / s.length() — 长度",
                    "s.empty() — 是否为空",
                    "s[i] / s.at(i) — 访问字符",
                    "s.front() / s.back() — 首/尾字符",
                    "s.find(str) — 查找子串，返回位置或 npos",
                    "s.rfind(str) — 从后往前查找",
                    "s.find_first_of(chars) — 查找任一字符首次出现",
                    "s.find_last_of(chars) — 查找任一字符末次出现",
                    "s.substr(pos, len) — 取子串",
                    "s.replace(pos, len, str) — 替换",
                    "s.insert(pos, str) — 插入",
                    "s.erase(pos, len) — 删除",
                    "s.compare(str) — 比较（<0/=0/>0）",
                    "s.c_str() — 转 C 字符串（const char*）",
                    "s.data() — 底层字符数组",
                    "s.clear() — 清空",
                    "s.resize(n) — 改变大小",
                    "s.reserve(n) — 预留容量",
                    "s.swap(other) — 交换",
                    "to_string(num) — 数字转字符串（全局函数）",
                    "stoi(s) / stol(s) / stoll(s) — 字符串转整数",
                    "stof(s) / stod(s) — 字符串转浮点数",
                    "getline(cin, s) — 读取整行",
                ],
                "example": """#include <iostream>
#include <string>
#include <algorithm>

using namespace std;

int main() {
    // 创建与基本操作
    string s1 = "Hello";
    string s2("World");
    string s3(5, 'a'); // "aaaaa"

    // 拼接
    string greeting = s1 + ", " + s2 + "!";
    cout << greeting << endl; // Hello, World!
    greeting += " How are you?";
    greeting.append(" Fine.");

    // 长度与访问
    cout << "长度: " << greeting.size() << endl;
    cout << "首字符: " << greeting[0] << endl;
    cout << "尾字符: " << greeting.back() << endl;
    greeting[0] = 'h'; // 修改

    // 查找
    string text = "The quick brown fox jumps over the lazy dog";
    size_t pos = text.find("fox");
    if (pos != string::npos) {
        cout << "找到 fox 在位置 " << pos << endl;
    }
    pos = text.find("cat");
    if (pos == string::npos) cout << "未找到 cat" << endl;

    // 从后查找
    pos = text.rfind("the");
    cout << "最后一个 the 在位置 " << pos << endl;

    // 查找任一字符
    pos = text.find_first_of("aeiou");
    cout << "第一个元音在位置 " << pos << endl;

    // 子串
    string sub = text.substr(4, 5); // 从位置4开始5个字符
    cout << "子串: " << sub << endl; // quick

    // 替换
    string s = "I like C++";
    s.replace(7, 3, "Python"); // 从位置7开始3个字符替换
    cout << s << endl; // I like Python

    // 插入与删除
    s.insert(0, "Yes, ");
    cout << s << endl; // Yes, I like Python
    s.erase(0, 5); // 删除前5个字符
    cout << s << endl;

    // 比较
    cout << (s1 == "Hello") << endl; // 1 (true)
    cout << s1.compare("Hello") << endl; // 0
    cout << ("apple" < "banana") << endl; // 1

    // 大小写转换（用算法库）
    string str = "Hello World";
    transform(str.begin(), str.end(), str.begin(), ::toupper);
    cout << str << endl; // HELLO WORLD
    transform(str.begin(), str.end(), str.begin(), ::tolower);
    cout << str << endl; // hello world

    // 去除首尾空格（示例）
    string trim_example = "  hello  ";
    size_t start = trim_example.find_first_not_of(" \\t\\n");
    size_t end = trim_example.find_last_not_of(" \\t\\n");
    string trimmed = trim_example.substr(start, end - start + 1);
    cout << "[" << trimmed << "]" << endl; // [hello]

    // 数字与字符串转换
    int num = 42;
    string num_str = to_string(num); // "42"
    double pi = 3.14159;
    string pi_str = to_string(pi); // "3.141590"

    int parsed_int = stoi("123");
    long parsed_long = stol("1234567890");
    double parsed_double = stod("3.14");
    cout << parsed_int << " " << parsed_long << " " << parsed_double << endl;

    // 分割字符串（用 stringstream）
    #include <sstream>
    string csv = "apple,banana,orange,grape";
    stringstream ss(csv);
    string token;
    while (getline(ss, token, ',')) {
        cout << token << " ";
    }
    cout << endl;

    // C 字符串互操作
    const char* cstr = s.c_str(); // 传递给 C API
    printf("%s\\n", cstr);

    return 0;
}""",
                "tips": "string 是可变的，修改不会创建新对象（除非赋值）；find 返回 size_t（无符号），未找到返回 string::npos（通常是 -1 的无符号表示），比较时注意类型；substr 的第二个参数是长度不是结束位置；c_str() 返回的指针在 string 修改后失效，不要长期保存；+ 运算符拼接大量字符串效率低，用 ostringstream 或 reserve + append；to_string 浮点数可能有多余的 0，需要格式化用 ostringstream + fixed + setprecision；stoi 等函数遇到非数字会抛 invalid_argument 或 out_of_range，需要 try-catch；string 的 size() 和 length() 完全等价。",
            },
            {
                "name": "map / unordered_map — 关联容器",
                "desc": "std::map 是有序关联容器（红黑树实现），按 key 排序；std::unordered_map 是哈希表实现，平均 O(1) 查找。两者都存储键值对，key 唯一。",
                "functions": [
                    "map<K,V> m / unordered_map<K,V> m — 创建空映射",
                    "m[key] = value — 插入或更新（key 不存在会默认构造）",
                    "m.insert({key, value}) — 插入（key 存在不覆盖）",
                    "m.emplace(key, value) — 原位构造插入",
                    "m.at(key) — 访问（key 不存在抛 out_of_range）",
                    "m[key] — 访问（key 不存在会插入默认值）",
                    "m.find(key) — 查找，返回迭代器或 end()",
                    "m.count(key) — 统计 key 个数（0或1）",
                    "m.contains(key) — 是否包含（C++20）",
                    "m.erase(key) — 删除键值对",
                    "m.erase(iterator) — 删除迭代器指向的元素",
                    "m.size() — 元素个数",
                    "m.empty() — 是否为空",
                    "m.clear() — 清空",
                    "m.begin() / m.end() — 迭代器",
                    "范围 for: for (auto& [key, value] : m) （C++17 结构化绑定）",
                    "map 特有: m.lower_bound(key) / upper_bound(key) — 边界查找",
                    "unordered_map 特有: m.bucket_count() / m.load_factor() / m.rehash(n)",
                    "multimap / unordered_multimap — key 可重复的版本",
                ],
                "example": """#include <iostream>
#include <map>
#include <unordered_map>
#include <string>

using namespace std;

int main() {
    // ===== map（有序，红黑树）=====
    map<string, int> scores;

    // 插入
    scores["Alice"] = 95;
    scores["Bob"] = 87;
    scores.insert({"Charlie", 92});
    scores.emplace("David", 88);

    // 访问
    cout << scores["Alice"] << endl; // 95
    cout << scores.at("Bob") << endl; // 87
    // cout << scores.at("Eve") << endl; // 抛 out_of_range

    // 注意：scores["不存在的key"] 会插入默认值！
    // 检查存在性用 find 或 count
    if (scores.find("Eve") != scores.end()) {
        cout << "Eve 存在" << endl;
    }
    if (scores.count("Alice")) {
        cout << "Alice 存在" << endl;
    }

    // 遍历（map 按 key 字典序排列）
    cout << "=== map 遍历（有序）===" << endl;
    for (const auto& pair : scores) {
        cout << pair.first << ": " << pair.second << endl;
    }

    // C++17 结构化绑定
    for (const auto& [name, score] : scores) {
        cout << name << " -> " << score << endl;
    }

    // 修改
    scores["Bob"] = 90; // 更新

    // 删除
    scores.erase("David");
    auto it = scores.find("Charlie");
    if (it != scores.end()) scores.erase(it);

    // map 自定义排序（按 value 排序需要复制到 vector）
    vector<pair<string, int>> vec(scores.begin(), scores.end());
    sort(vec.begin(), vec.end(), [](const auto& a, const auto& b) {
        return a.second > b.second; // 按分数降序
    });

    // ===== unordered_map（无序，哈希表，更快）=====
    unordered_map<string, string> capitals;
    capitals["中国"] = "北京";
    capitals["美国"] = "华盛顿";
    capitals["日本"] = "东京";
    capitals["英国"] = "伦敦";

    cout << "=== unordered_map 遍历（无序）===" << endl;
    for (const auto& [country, capital] : capitals) {
        cout << country << ": " << capital << endl;
    }

    // 查找性能：unordered_map 平均 O(1)，map O(log n)
    if (capitals.contains("中国")) { // C++20
        cout << "中国首都是 " << capitals["中国"] << endl;
    }

    // 统计词频（经典应用）
    unordered_map<string, int> word_count;
    vector<string> words = {"apple", "banana", "apple", "orange", "banana", "apple"};
    for (const string& w : words) {
        word_count[w]++; // key 不存在时默认构造为 0，然后 ++
    }
    for (const auto& [word, count] : word_count) {
        cout << word << ": " << count << " 次" << endl;
    }

    // 自定义 key 类型的哈希（unordered_map 需要）
    // struct Point { int x, y; };
    // 需要提供 hash<Point> 特化或自定义哈希函数

    // multimap（key 可重复）
    multimap<string, int> mm;
    mm.insert({"A", 1});
    mm.insert({"A", 2});
    mm.insert({"B", 3});
    cout << "A 的个数: " << mm.count("A") << endl; // 2

    // 遍历 multimap 中某个 key 的所有值
    auto range = mm.equal_range("A");
    for (auto it = range.first; it != range.second; ++it) {
        cout << it->second << " ";
    }
    cout << endl;

    return 0;
}""",
                "tips": "map 按 key 升序排列（默认 less<K>），遍历是有序的；unordered_map 遍历顺序不确定，但平均查找更快；用 [] 访问不存在的 key 会插入默认值，这是常见 bug，检查存在性用 find/count/contains；map 的 key 必须可比较（需要 operator<），unordered_map 的 key 需要哈希函数和 operator==；自定义类型作为 unordered_map 的 key 需要提供 std::hash 特化；大量数据用 unordered_map，需要有序或范围查询用 map；erase(key) 返回删除的个数（0或1）；迭代器在修改其他元素时通常仍然有效（unordered_map rehash 时失效）。",
            },
            {
                "name": "memory — 智能指针",
                "desc": "C++11 引入的智能指针自动管理内存生命周期，避免内存泄漏和悬空指针。unique_ptr 独占所有权，shared_ptr 共享引用计数，weak_ptr 不增加引用计数。",
                "functions": [
                    "make_unique<T>(args) — 创建 unique_ptr（C++14）",
                    "make_shared<T>(args) — 创建 shared_ptr",
                    "unique_ptr<T> p — 独占所有权智能指针",
                    "shared_ptr<T> p — 共享所有权智能指针（引用计数）",
                    "weak_ptr<T> p — 弱引用，不增加引用计数",
                    "p.get() — 获取原始指针",
                    "p.reset() — 释放所有权（引用计数减1/置空）",
                    "p.reset(new T) — 重置为新对象",
                    "p.release() — 释放所有权并返回原始指针（unique_ptr）",
                    "p.use_count() — 引用计数（shared_ptr）",
                    "p.unique() — 是否唯一拥有（shared_ptr，C++17 弃用）",
                    "p.expired() — 引用计数是否为0（weak_ptr）",
                    "p.lock() — 提升为 shared_ptr（weak_ptr）",
                    "*p / p->member — 解引用和成员访问",
                    "if (p) — 检查是否非空",
                    "p.swap(other) — 交换所有权",
                    "动态数组: unique_ptr<T[]> / shared_ptr<T[]>（C++17）",
                    "自定义删除器: unique_ptr<T, Deleter>",
                    "enable_shared_from_this — 类成员函数返回 shared_ptr",
                ],
                "example": """#include <iostream>
#include <memory>
#include <vector>
#include <string>

using namespace std;

class Resource {
public:
    string name;
    Resource(string n) : name(n) { cout << name << " 构造" << endl; }
    ~Resource() { cout << name << " 析构" << endl; }
    void use() { cout << "使用 " << name << endl; }
};

int main() {
    // ===== unique_ptr（独占所有权，不可拷贝，可移动）=====
    {
        unique_ptr<Resource> p1 = make_unique<Resource>("A");
        p1->use();
        cout << "p1.get(): " << p1.get() << endl;

        // unique_ptr<Resource> p2 = p1; // 编译错误！不可拷贝
        unique_ptr<Resource> p2 = move(p1); // 移动所有权
        if (!p1) cout << "p1 已为空" << endl;
        p2->use();

        // 离开作用域自动析构（即使有异常也安全）
    }

    // unique_ptr 作为容器元素
    vector<unique_ptr<Resource>> resources;
    resources.push_back(make_unique<Resource>("R1"));
    resources.push_back(make_unique<Resource>("R2"));
    for (const auto& r : resources) r->use();

    // unique_ptr 动态数组
    unique_ptr<int[]> arr = make_unique<int[]>(5);
    for (int i = 0; i < 5; i++) arr[i] = i * i;
    for (int i = 0; i < 5; i++) cout << arr[i] << " ";
    cout << endl;

    // release() 返回原始指针并释放所有权（需要手动 delete，慎用）
    unique_ptr<Resource> p3 = make_unique<Resource>("手动");
    Resource* raw = p3.release();
    raw->use();
    delete raw; // 必须手动释放

    // ===== shared_ptr（共享所有权，引用计数）=====
    {
        shared_ptr<Resource> s1 = make_shared<Resource>("共享");
        cout << "引用计数: " << s1.use_count() << endl; // 1

        shared_ptr<Resource> s2 = s1; // 拷贝，引用计数+1
        cout << "引用计数: " << s1.use_count() << endl; // 2

        {
            shared_ptr<Resource> s3 = s1;
            cout << "引用计数: " << s1.use_count() << endl; // 3
        } // s3 析构，引用计数-1

        cout << "引用计数: " << s1.use_count() << endl; // 2
        s2.reset(); // 手动释放，引用计数-1
        cout << "引用计数: " << s1.use_count() << endl; // 1
    } // s1 析构，引用计数变0，对象析构

    // shared_ptr 循环引用问题（需要 weak_ptr 解决）
    struct Node {
        string name;
        shared_ptr<Node> next; // 如果互相指向会循环引用
        weak_ptr<Node> prev;    // 用 weak_ptr 避免循环引用
        Node(string n) : name(n) { cout << n << " 构造" << endl; }
        ~Node() { cout << name << " 析构" << endl; }
    };

    {
        auto node1 = make_shared<Node>("节点1");
        auto node2 = make_shared<Node>("节点2");
        node1->next = node2;      // shared_ptr 引用计数+1
        node2->prev = node1;      // weak_ptr 不增加引用计数
        // 离开作用域正确析构（如果两个都是 shared_ptr 互相指向会内存泄漏）
    }

    // weak_ptr 使用
    weak_ptr<Resource> wp;
    {
        auto sp = make_shared<Resource>("弱引用");
        wp = sp; // 不增加引用计数
        cout << "wp.expired(): " << wp.expired() << endl; // false
        if (auto locked = wp.lock()) { // 提升为 shared_ptr
            locked->use();
        }
    }
    cout << "wp.expired(): " << wp.expired() << endl; // true（对象已析构）

    // ===== 为什么用智能指针 =====
    // 传统 new/delete 的问题：
    // 1. 忘记 delete → 内存泄漏
    // 2. 异常导致 delete 不执行 → 内存泄漏
    // 3. 重复 delete → 崩溃
    // 4. 悬空指针 → 未定义行为
    // 智能指针 RAII 机制自动管理，避免以上问题

    cout << "程序结束" << endl;
    return 0;
}""",
                "tips": "优先用 make_unique/make_shared，不要直接用 new 构造智能指针（异常安全+效率）；unique_ptr 几乎零开销，是默认选择；shared_ptr 有引用计数开销（约 2 倍指针大小+原子操作），只在需要共享时用；shared_ptr 循环引用会导致内存泄漏，用 weak_ptr 打破循环；weak_ptr 不能直接解引用，必须先 lock() 提升为 shared_ptr 并检查是否为空；get() 返回的原始指针不拥有所有权，不要 delete 它；自定义删除器用于管理非 new 分配的资源（如文件句柄、FILE*）；enable_shared_from_this 用于类成员函数需要返回指向自身的 shared_ptr；不要用同一个原始指针构造多个 shared_ptr（会重复释放）。",
            },
        ],
    }

_more = _more_modules()
for _k, _v in _more.items():
    if _k not in LANG_MODULES:
        LANG_MODULES[_k] = _v

del _more, _more_modules


def _more_modules2():
    return {
        "java": [
            {
                "name": "java.util — 集合框架",
                "desc": "Java 集合框架提供 List、Set、Map、Queue 等接口和实现类，是 Java 开发最核心的数据结构库，涵盖动态数组、链表、哈希表、树、队列等。",
                "functions": [
                    "ArrayList<E> — 动态数组，随机访问快，中间增删慢",
                    "LinkedList<E> — 双向链表，头尾增删快，随机访问慢",
                    "HashMap<K,V> — 哈希表，键值对，平均 O(1) 查找",
                    "LinkedHashMap — 保持插入顺序的 HashMap",
                    "TreeMap — 红黑树实现，按 key 排序",
                    "HashSet<E> — 基于 HashMap 的不重复集合",
                    "TreeSet — 有序不重复集合",
                    "LinkedHashSet — 保持插入顺序的 Set",
                    "PriorityQueue — 优先队列（堆）",
                    "ArrayDeque — 双端队列",
                    "Collections.sort(list) — 排序",
                    "Collections.reverse(list) — 反转",
                    "Collections.shuffle(list) — 打乱",
                    "Collections.max/min — 最大最小值",
                    "Collections.unmodifiableList — 不可变视图",
                    "list.add(e) / add(i,e) / get(i) / set(i,e) / remove(i)",
                    "map.put(k,v) / get(k) / containsKey(k) / remove(k) / keySet() / values() / entrySet()",
                    "set.add(e) / contains(e) / remove(e) / size()",
                    "迭代器: Iterator<E> it = list.iterator(); while(it.hasNext())",
                    "增强 for: for (E e : list)",
                    "泛型: List<String> list = new ArrayList<>();（钻石运算符 Java 7+）",
                ],
                "example": """import java.util.*;

public class CollectionDemo {
    public static void main(String[] args) {
        // ===== List =====
        List<String> list = new ArrayList<>();
        list.add("Apple");
        list.add("Banana");
        list.add(1, "Cherry"); // 在索引1插入
        System.out.println(list.get(0)); // Apple
        System.out.println(list.size()); // 3
        list.remove("Banana");

        // 遍历
        for (String s : list) System.out.print(s + " ");
        System.out.println();
        for (int i = 0; i < list.size(); i++) System.out.print(list.get(i) + " ");
        System.out.println();
        Iterator<String> it = list.iterator();
        while (it.hasNext()) System.out.print(it.next() + " ");
        System.out.println();

        // 排序
        List<Integer> nums = new ArrayList<>(Arrays.asList(5, 2, 8, 1, 9));
        Collections.sort(nums); // 升序
        Collections.sort(nums, Collections.reverseOrder()); // 降序
        // Java 8+ Lambda
        nums.sort((a, b) -> a - b);
        nums.sort(Comparator.reverseOrder());

        // ===== Map =====
        Map<String, Integer> scores = new HashMap<>();
        scores.put("Alice", 95);
        scores.put("Bob", 87);
        scores.put("Charlie", 92);
        System.out.println(scores.get("Alice")); // 95
        System.out.println(scores.getOrDefault("Eve", 0)); // 0
        System.out.println(scores.containsKey("Bob")); // true

        // 遍历 Map
        for (Map.Entry<String, Integer> entry : scores.entrySet()) {
            System.out.println(entry.getKey() + ": " + entry.getValue());
        }
        // Java 8+ forEach
        scores.forEach((k, v) -> System.out.println(k + " -> " + v));

        // 统计词频
        Map<String, Integer> freq = new HashMap<>();
        List<String> words = Arrays.asList("a", "b", "a", "c", "b", "a");
        for (String w : words) {
            freq.merge(w, 1, Integer::sum); // Java 8+
        }
        System.out.println(freq); // {a=3, b=2, c=1}

        // ===== Set =====
        Set<String> set = new HashSet<>();
        set.add("a"); set.add("b"); set.add("a"); // 重复元素被忽略
        System.out.println(set.size()); // 2
        System.out.println(set.contains("a")); // true

        // 去重
        List<Integer> withDup = Arrays.asList(1, 2, 2, 3, 3, 3);
        Set<Integer> unique = new HashSet<>(withDup);
        System.out.println(unique); // [1, 2, 3]

        // ===== Queue / Stack =====
        Queue<Integer> queue = new LinkedList<>();
        queue.offer(1); queue.offer(2); queue.offer(3);
        System.out.println(queue.poll()); // 1（出队）
        System.out.println(queue.peek()); // 2（查看队首）

        Deque<Integer> stack = new ArrayDeque<>();
        stack.push(1); stack.push(2); stack.push(3);
        System.out.println(stack.pop()); // 3（出栈）

        // 优先队列（小顶堆）
        PriorityQueue<Integer> pq = new PriorityQueue<>();
        pq.offer(5); pq.offer(1); pq.offer(3);
        System.out.println(pq.poll()); // 1（最小元素）

        // 不可变集合（Java 9+）
        List<String> immutable = List.of("a", "b", "c");
        Map<String, Integer> imap = Map.of("a", 1, "b", 2);
        // immutable.add("d"); // 抛 UnsupportedOperationException
    }
}""",
                "tips": "ArrayList 是默认选择，随机访问 O(1)，中间插入 O(n)；LinkedList 适合频繁头尾增删，但随机访问慢；HashMap 允许 null key/value，HashTable 不允许且已过时；遍历集合时不要用 list.remove()，用 Iterator.remove() 或 ConcurrentModificationException；Java 8+ 用 Stream API 处理集合更简洁；Collections 工具类提供排序、反转、同步包装等静态方法；泛型在编译时擦除，运行时不可用 getClass().getGenericComponentType；选择集合：有序可重复用 List，无序不重复用 HashSet，有序不重复用 TreeSet，键值对用 HashMap，排序键值对用 TreeMap。",
            },
            {
                "name": "java.io / java.nio — 文件与IO",
                "desc": "Java IO 提供字节流和字符流处理文件读写；NIO 提供更高效的通道和缓冲区，支持非阻塞 IO。Java 7+ 的 Files/Paths 工具类简化了文件操作。",
                "functions": [
                    "File — 文件/目录对象（传统）",
                    "Files.readAllBytes(path) / readAllLines — 读取全部内容",
                    "Files.write(path, bytes, options) — 写入文件",
                    "Files.lines(path) — 流式读取行（Java 8+）",
                    "Files.copy / move / delete / exists / createDirectory",
                    "Paths.get(...) — 创建 Path 对象",
                    "FileInputStream / FileOutputStream — 字节文件流",
                    "FileReader / FileWriter — 字符文件流",
                    "BufferedReader / BufferedWriter — 缓冲字符流",
                    "InputStreamReader / OutputStreamWriter — 桥接字节字符流",
                    "DataInputStream / DataOutputStream — 基本类型数据流",
                    "ObjectInputStream / ObjectOutputStream — 对象序列化",
                    "Scanner — 文本扫描器（读取基本类型）",
                    "PrintWriter — 格式化输出",
                    "ByteArrayInputStream / ByteArrayOutputStream — 内存流",
                    "StandardCharsets.UTF_8 — 标准字符集常量",
                    "try-with-resources — 自动关闭流（Java 7+）",
                    "Charset / StandardCharsets — 字符集处理",
                ],
                "example": """import java.io.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.util.*;
import java.util.stream.*;

public class IODemo {
    public static void main(String[] args) throws IOException {
        Path path = Paths.get("test.txt");

        // ===== 简单读写（Java 7+ NIO Files）=====
        // 写入文件
        List<String> lines = Arrays.asList("第一行", "第二行", "第三行");
        Files.write(path, lines, StandardCharsets.UTF_8);

        // 读取全部行
        List<String> readLines = Files.readAllLines(path, StandardCharsets.UTF_8);
        for (String line : readLines) System.out.println(line);

        // 读取为字符串
        String content = new String(Files.readAllBytes(path), StandardCharsets.UTF_8);
        System.out.println(content);

        // 流式读取（大文件，Java 8+）
        try (Stream<String> stream = Files.lines(path, StandardCharsets.UTF_8)) {
            stream.filter(l -> l.contains("第"))
                  .forEach(System.out::println);
        }

        // 追加写入
        Files.write(path, Collections.singletonList("追加行"),
                    StandardCharsets.UTF_8, StandardOpenOption.APPEND);

        // ===== 传统 IO（try-with-resources 自动关闭）=====
        // 字符流读写文本
        try (BufferedWriter writer = new BufferedWriter(
                new FileWriter("output.txt", StandardCharsets.UTF_8))) {
            writer.write("Hello, World!");
            writer.newLine();
            writer.write("第二行");
        }

        try (BufferedReader reader = new BufferedReader(
                new FileReader("output.txt", StandardCharsets.UTF_8))) {
            String line;
            while ((line = reader.readLine()) != null) {
                System.out.println(line);
            }
        }

        // 字节流读写二进制
        try (FileInputStream in = new FileInputStream("input.bin");
             FileOutputStream out = new FileOutputStream("output.bin")) {
            byte[] buffer = new byte[4096];
            int bytesRead;
            while ((bytesRead = in.read(buffer)) != -1) {
                out.write(buffer, 0, bytesRead);
            }
        }

        // ===== Scanner 读取输入 =====
        Scanner scanner = new Scanner(System.in);
        System.out.print("输入姓名: ");
        String name = scanner.nextLine();
        System.out.print("输入年龄: ");
        int age = scanner.nextInt();
        System.out.println(name + ", " + age + " 岁");
        // scanner.close(); // System.in 一般不关闭

        // 从字符串扫描
        Scanner strScanner = new Scanner("10 20 30");
        while (strScanner.hasNextInt()) {
            System.out.print(strScanner.nextInt() + " ");
        }
        System.out.println();

        // ===== 文件操作 =====
        Path dir = Paths.get("mydir");
        Files.createDirectories(dir);
        System.out.println(Files.exists(dir)); // true
        System.out.println(Files.isDirectory(dir)); // true

        // 复制、移动、删除
        Files.copy(path, Paths.get("copy.txt"), StandardCopyOption.REPLACE_EXISTING);
        Files.move(Paths.get("copy.txt"), Paths.get("moved.txt"),
                   StandardCopyOption.REPLACE_EXISTING);
        Files.deleteIfExists(Paths.get("moved.txt"));

        // 遍历目录
        try (Stream<Path> paths = Files.walk(Paths.get("."))) {
            paths.filter(Files::isRegularFile)
                 .filter(p -> p.toString().endsWith(".txt"))
                 .forEach(System.out::println);
        }

        // 获取文件属性
        BasicFileAttributes attrs = Files.readAttributes(path, BasicFileAttributes.class);
        System.out.println("大小: " + attrs.size() + " bytes");
        System.out.println("创建时间: " + attrs.creationTime());
        System.out.println("最后修改: " + attrs.lastModifiedTime());

        // ===== 对象序列化 =====
        // 需要类实现 Serializable 接口
        // try (ObjectOutputStream oos = new ObjectOutputStream(new FileOutputStream("obj.dat"))) {
        //     oos.writeObject(new Person("Alice", 25));
        // }
        // try (ObjectInputStream ois = new ObjectInputStream(new FileInputStream("obj.dat"))) {
        //     Person p = (Person) ois.readObject();
        // }
    }
}""",
                "tips": "始终用 try-with-resources 自动关闭流，不要手动 close()（异常时可能泄漏）；文本文件用字符流（Reader/Writer），二进制文件用字节流（InputStream/OutputStream）；BufferedReader/BufferedWriter 缓冲流提高 IO 性能；Java 11+ 新增 Files.readString/writeString 更简洁；Scanner 用 nextInt() 后残留换行符，后续 nextLine() 会读到空行；大文件不要用 readAllLines（内存溢出），用 lines() 流式处理；序列化需要 serialVersionUID 防止版本不兼容；路径分隔符用 File.separator 或 Paths.get 跨平台；字符集始终显式指定 UTF-8，不要依赖平台默认编码。",
            },
            {
                "name": "java.util.stream — Stream API",
                "desc": "Java 8 引入的 Stream API 提供函数式风格的集合数据处理，支持过滤、映射、归约、分组、并行等操作，让集合处理更简洁优雅。",
                "functions": [
                    "collection.stream() — 创建串行流",
                    "collection.parallelStream() — 创建并行流",
                    "Stream.of(...) — 从值创建流",
                    "Arrays.stream(array) — 从数组创建流",
                    "IntStream.range(start, end) / rangeClosed — 整数范围流",
                    "filter(predicate) — 过滤元素",
                    "map(function) — 映射转换",
                    "mapToInt / mapToDouble — 映射为基本类型流",
                    "flatMap(function) — 扁平化映射（一对多）",
                    "sorted() / sorted(comparator) — 排序",
                    "distinct() — 去重",
                    "limit(n) — 限制元素个数",
                    "skip(n) — 跳过前 n 个",
                    "peek(consumer) — 查看元素（调试用）",
                    "collect(collector) — 收集结果（终端操作）",
                    "Collectors.toList() / toSet() / toMap() — 收集为集合",
                    "Collectors.joining(delimiter) — 连接为字符串",
                    "Collectors.groupingBy(classifier) — 分组",
                    "Collectors.partitioningBy(predicate) — 分区（true/false）",
                    "Collectors.counting() / summingInt / averagingInt — 聚合",
                    "Collectors.maxBy / minBy — 最大最小",
                    "reduce(identity, accumulator) — 归约",
                    "forEach(consumer) — 遍历（终端操作）",
                    "count() — 元素个数",
                    "anyMatch / allMatch / noneMatch — 匹配判断",
                    "findFirst / findAny — 查找元素",
                    "max / min / sum / average — 数值流操作",
                    "toArray() — 转为数组",
                ],
                "example": """import java.util.*;
import java.util.stream.*;

public class StreamDemo {
    static class Person {
        String name; int age; String city;
        Person(String n, int a, String c) { name=n; age=a; city=c; }
        public String toString() { return name + "(" + age + ")"; }
    }

    public static void main(String[] args) {
        List<Person> people = Arrays.asList(
            new Person("Alice", 25, "北京"),
            new Person("Bob", 30, "上海"),
            new Person("Charlie", 35, "北京"),
            new Person("Diana", 28, "广州"),
            new Person("Eve", 32, "上海")
        );

        // ===== 过滤 + 映射 + 收集 =====
        List<String> names = people.stream()
            .filter(p -> p.age >= 30)          // 过滤年龄>=30
            .map(p -> p.name)                    // 提取姓名
            .sorted()                             // 排序
            .collect(Collectors.toList());       // 收集为 List
        System.out.println(names); // [Bob, Charlie, Eve]

        // ===== 归约 reduce =====
        int totalAge = people.stream()
            .mapToInt(p -> p.age)
            .sum(); // 或 .reduce(0, Integer::sum)
        System.out.println("总年龄: " + totalAge); // 150

        double avgAge = people.stream()
            .mapToInt(p -> p.age)
            .average()
            .orElse(0);
        System.out.println("平均年龄: " + avgAge); // 30.0

        // ===== 分组 groupingBy =====
        Map<String, List<Person>> byCity = people.stream()
            .collect(Collectors.groupingBy(p -> p.city));
        byCity.forEach((city, list) ->
            System.out.println(city + ": " + list));

        // 分组 + 聚合（每个城市的平均年龄）
        Map<String, Double> avgByCity = people.stream()
            .collect(Collectors.groupingBy(
                p -> p.city,
                Collectors.averagingInt(p -> p.age)));
        System.out.println(avgByCity); // {北京=30.0, 上海=31.0, 广州=28.0}

        // 分组 + 计数
        Map<String, Long> countByCity = people.stream()
            .collect(Collectors.groupingBy(p -> p.city, Collectors.counting()));
        System.out.println(countByCity); // {北京=2, 上海=2, 广州=1}

        // ===== 分区 partitioningBy =====
        Map<Boolean, List<Person>> partitioned = people.stream()
            .collect(Collectors.partitioningBy(p -> p.age >= 30));
        System.out.println("30岁以上: " + partitioned.get(true));
        System.out.println("30岁以下: " + partitioned.get(false));

        // ===== 连接字符串 joining =====
        String allNames = people.stream()
            .map(p -> p.name)
            .collect(Collectors.joining(", ", "[", "]"));
        System.out.println(allNames); // [Alice, Bob, Charlie, Diana, Eve]

        // ===== toMap =====
        Map<String, Integer> nameToAge = people.stream()
            .collect(Collectors.toMap(p -> p.name, p -> p.age));
        System.out.println(nameToAge.get("Alice")); // 25

        // ===== 匹配判断 =====
        boolean allAdult = people.stream().allMatch(p -> p.age >= 18);
        boolean anyBeijing = people.stream().anyMatch(p -> p.city.equals("北京"));
        boolean noneOld = people.stream().noneMatch(p -> p.age > 100);
        System.out.println(allAdult + " " + anyBeijing + " " + noneOld);

        // ===== 查找 =====
        Optional<Person> first = people.stream()
            .filter(p -> p.city.equals("上海"))
            .findFirst();
        first.ifPresent(p -> System.out.println("第一个上海人: " + p.name));

        // ===== flatMap 扁平化 =====
        List<List<Integer>> nested = Arrays.asList(
            Arrays.asList(1, 2), Arrays.asList(3, 4), Arrays.asList(5, 6));
        List<Integer> flat = nested.stream()
            .flatMap(List::stream)
            .collect(Collectors.toList());
        System.out.println(flat); // [1, 2, 3, 4, 5, 6]

        // ===== 基本类型流 =====
        int sum = IntStream.rangeClosed(1, 100).sum(); // 1到100求和
        System.out.println("1+2+...+100 = " + sum); // 5050

        IntStream.range(1, 10)
            .filter(n -> n % 2 == 0)
            .forEach(n -> System.out.print(n + " ")); // 2 4 6 8
        System.out.println();

        // ===== 并行流 =====
        long count = people.parallelStream()
            .filter(p -> p.age >= 30)
            .count();
        System.out.println("并行统计: " + count);

        // ===== 去重 + 限制 =====
        List<Integer> numbers = Arrays.asList(3, 1, 4, 1, 5, 9, 2, 6, 5, 3);
        List<Integer> top3 = numbers.stream()
            .distinct()
            .sorted(Comparator.reverseOrder())
            .limit(3)
            .collect(Collectors.toList());
        System.out.println("前3大: " + top3); // [9, 6, 5]
    }
}""",
                "tips": "Stream 操作分中间操作（lazy，返回 Stream）和终端操作（触发计算）；中间操作不会立即执行，直到终端操作才触发；Stream 只能消费一次，遍历后不能再用；collect 是最常用的终端操作，Collectors 提供丰富的收集器；并行流 parallelStream 适合 CPU 密集型、无状态、可并行的操作，IO 密集型不适合；map 是一对一转换，flatMap 是一对多并扁平化；Optional 用于避免 NullPointerException；peek 主要用于调试，不要用于业务逻辑；Stream 不会修改原始集合；大数据量用并行流但注意线程安全；方法引用（::）比 Lambda 更简洁。",
            },
            {
                "name": "java.util.concurrent — 并发编程",
                "desc": "Java 并发包提供线程池、并发集合、原子类、锁、同步工具等，是 Java 多线程编程的核心库，帮助编写高效、线程安全的并发代码。",
                "functions": [
                    "ExecutorService — 线程池接口",
                    "Executors.newFixedThreadPool(n) — 固定大小线程池",
                    "Executors.newCachedThreadPool() — 缓存线程池",
                    "Executors.newSingleThreadExecutor() — 单线程池",
                    "Executors.newScheduledThreadPool — 定时任务线程池",
                    "ThreadPoolExecutor — 自定义线程池",
                    "Future<T> — 异步任务结果",
                    "Callable<T> — 有返回值的任务",
                    "Runnable — 无返回值任务",
                    "CompletableFuture — 可组合的异步任务（Java 8+）",
                    "CountDownLatch — 倒计时门闩",
                    "CyclicBarrier — 循环栅栏",
                    "Semaphore — 信号量",
                    "ReentrantLock — 可重入锁",
                    "ReadWriteLock / ReentrantReadWriteLock — 读写锁",
                    "Condition — 条件变量",
                    "AtomicInteger / AtomicLong / AtomicReference — 原子类",
                    "ConcurrentHashMap — 线程安全 HashMap",
                    "CopyOnWriteArrayList — 写时复制列表",
                    "BlockingQueue / ArrayBlockingQueue / LinkedBlockingQueue — 阻塞队列",
                    "ConcurrentLinkedQueue — 无界非阻塞队列",
                    "ThreadLocal — 线程本地变量",
                    "volatile — 可见性关键字",
                    "synchronized — 内置锁",
                    "Thread.sleep / join / interrupt — 线程基础操作",
                ],
                "example": """import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.*;

public class ConcurrentDemo {
    public static void main(String[] args) throws Exception {
        // ===== 线程池 + Callable + Future =====
        ExecutorService executor = Executors.newFixedThreadPool(4);

        List<Callable<Integer>> tasks = new ArrayList<>();
        for (int i = 1; i <= 10; i++) {
            final int n = i;
            tasks.add(() -> {
                Thread.sleep(100);
                return n * n;
            });
        }

        // 提交所有任务
        List<Future<Integer>> futures = executor.invokeAll(tasks);
        int total = 0;
        for (Future<Integer> f : futures) {
            total += f.get(); // 阻塞等待结果
        }
        System.out.println("平方和: " + total); // 385

        // 单个任务
        Future<String> future = executor.submit(() -> {
            Thread.sleep(500);
            return "异步任务结果";
        });
        System.out.println("做其他事...");
        System.out.println(future.get()); // 阻塞等待

        // 超时获取
        try {
            String result = future.get(1, TimeUnit.SECONDS);
        } catch (TimeoutException e) {
            System.out.println("超时");
        }

        executor.shutdown(); // 关闭线程池（等待任务完成）
        // executor.shutdownNow(); // 立即关闭

        // ===== CompletableFuture（Java 8+ 可组合异步）=====
        CompletableFuture<String> cf1 = CompletableFuture.supplyAsync(() -> {
            try { Thread.sleep(200); } catch (InterruptedException e) {}
            return "Hello";
        });

        CompletableFuture<String> cf2 = cf1
            .thenApply(s -> s + ", World!")       // 转换
            .thenApply(String::toUpperCase)         // 再转换
            .exceptionally(ex -> "出错: " + ex.getMessage()); // 异常处理

        System.out.println(cf2.get()); // HELLO, WORLD!

        // 组合两个异步任务
        CompletableFuture<String> a = CompletableFuture.supplyAsync(() -> "A");
        CompletableFuture<String> b = CompletableFuture.supplyAsync(() -> "B");
        CompletableFuture<String> combined = a.thenCombine(b, (x, y) -> x + y);
        System.out.println(combined.get()); // AB

        // 等待所有完成
        CompletableFuture<Void> all = CompletableFuture.allOf(cf1, a, b);
        all.get();

        // ===== 原子类（无锁线程安全）=====
        AtomicInteger counter = new AtomicInteger(0);
        ExecutorService pool = Executors.newFixedThreadPool(10);
        for (int i = 0; i < 1000; i++) {
            pool.submit(counter::incrementAndGet);
        }
        pool.shutdown();
        pool.awaitTermination(10, TimeUnit.SECONDS);
        System.out.println("原子计数: " + counter.get()); // 1000

        // ===== 并发集合 =====
        ConcurrentHashMap<String, Integer> map = new ConcurrentHashMap<>();
        map.put("key", 1);
        map.compute("key", (k, v) -> v + 1); // 原子更新
        map.merge("newKey", 1, Integer::sum);

        CopyOnWriteArrayList<String> list = new CopyOnWriteArrayList<>();
        // 读多写少场景，读无锁，写时复制整个数组

        // ===== 阻塞队列（生产者消费者）=====
        BlockingQueue<Integer> queue = new ArrayBlockingQueue<>(100);

        // 生产者
        Thread producer = new Thread(() -> {
            try {
                for (int i = 0; i < 10; i++) {
                    queue.put(i); // 队列满时阻塞
                    System.out.println("生产: " + i);
                }
            } catch (InterruptedException e) {}
        });

        // 消费者
        Thread consumer = new Thread(() -> {
            try {
                for (int i = 0; i < 10; i++) {
                    int val = queue.take(); // 队列空时阻塞
                    System.out.println("消费: " + val);
                }
            } catch (InterruptedException e) {}
        });

        producer.start();
        consumer.start();
        producer.join();
        consumer.join();

        // ===== CountDownLatch（等待多个线程完成）=====
        int threadCount = 5;
        CountDownLatch latch = new CountDownLatch(threadCount);
        ExecutorService latchPool = Executors.newFixedThreadPool(threadCount);
        for (int i = 0; i < threadCount; i++) {
            latchPool.submit(() -> {
                try {
                    System.out.println(Thread.currentThread().getName() + " 执行");
                } finally {
                    latch.countDown(); // 计数减1
                }
            });
        }
        latch.await(); // 等待计数归零
        System.out.println("所有线程完成");
        latchPool.shutdown();

        // ===== ReentrantLock（显式锁）=====
        ReentrantLock lock = new ReentrantLock();
        lock.lock();
        try {
            // 临界区
        } finally {
            lock.unlock(); // 必须在 finally 中释放
        }

        // 尝试获取锁（带超时）
        if (lock.tryLock(1, TimeUnit.SECONDS)) {
            try {
                // 临界区
            } finally {
                lock.unlock();
            }
        }

        // ===== 读写锁（读多写少）=====
        ReentrantReadWriteLock rwLock = new ReentrantReadWriteLock();
        rwLock.readLock().lock();  // 读锁（多个线程可同时持有）
        try { /* 读操作 */ } finally { rwLock.readLock().unlock(); }

        rwLock.writeLock().lock(); // 写锁（独占）
        try { /* 写操作 */ } finally { rwLock.writeLock().unlock(); }

        // ===== Semaphore（控制并发数）=====
        Semaphore sem = new Semaphore(3); // 最多3个并发
        sem.acquire(); // 获取许可
        try { /* 受限操作 */ } finally { sem.release(); }

        // ===== ThreadLocal（线程本地变量）=====
        ThreadLocal<SimpleDateFormat> tl = ThreadLocal.withInitial(
            () -> new SimpleDateFormat("yyyy-MM-dd"));
        // 每个线程有自己的 SimpleDateFormat 实例，避免线程安全问题
    }
}""",
                "tips": "线程池必须 shutdown()，否则 JVM 不会退出；用 Executors 工厂方法创建简单线程池，生产环境用 ThreadPoolExecutor 自定义参数（核心线程数、最大线程数、队列、拒绝策略）；Future.get() 会阻塞，建议带超时；CompletableFuture 是 Java 8+ 异步编程首选，支持链式调用和组合；synchronized 是可重入内置锁，简单场景够用；ReentrantLock 支持公平锁、超时、可中断，复杂场景用；ConcurrentHashMap 不允许 null key/value；CopyOnWriteArrayList 适合读多写少，写操作开销大；BlockingQueue 是生产者消费者模式的首选；ThreadLocal 使用后必须 remove()，否则内存泄漏；volatile 保证可见性但不保证原子性，i++ 不是原子操作；避免用 Thread.stop()（已废弃），用 interrupt() 协作式中断。",
            },
            {
                "name": "java.time — 日期时间 API（Java 8+）",
                "desc": "Java 8 引入的全新日期时间 API，不可变、线程安全，取代了旧的 Date/Calendar。提供 LocalDate、LocalTime、LocalDateTime、ZonedDateTime、Duration、Period 等类。",
                "functions": [
                    "LocalDate.now() — 当前日期",
                    "LocalDate.of(year, month, day) — 指定日期",
                    "LocalDate.parse(str, formatter) — 解析日期",
                    "LocalTime.now() / of(hour, minute, second) — 时间",
                    "LocalDateTime.now() / of(date, time) — 日期时间",
                    "ZonedDateTime — 带时区的日期时间",
                    "Instant — 时间戳（UTC）",
                    "Duration — 时间间隔（秒/纳秒）",
                    "Period — 日期间隔（年/月/日）",
                    "DateTimeFormatter — 格式化/解析",
                    "dt.plusDays(n) / minusDays(n) — 加减天数",
                    "dt.plusWeeks/Months/Years — 加减周/月/年",
                    "dt.withYear/Month/Day — 修改字段",
                    "dt.getYear/getMonthValue/getDayOfMonth — 获取字段",
                    "dt.getDayOfWeek / getDayOfYear — 星期/年内第几天",
                    "dt.isBefore / isAfter / isEqual — 比较",
                    "dt.until(other, ChronoUnit.DAYS) — 计算间隔",
                    "dt.format(formatter) — 格式化",
                    "ZoneId.of(\"Asia/Shanghai\") — 时区",
                    "Clock — 时钟（可注入测试）",
                    "TemporalAdjusters — 时间调整器（firstDayOfMonth等）",
                    "ChronoUnit — 时间单位枚举",
                ],
                "example": """import java.time.*;
import java.time.format.*;
import java.time.temporal.*;

public class TimeDemo {
    public static void main(String[] args) {
        // ===== LocalDate（日期，无时区）=====
        LocalDate today = LocalDate.now();
        System.out.println("今天: " + today); // 2024-03-15

        LocalDate birthday = LocalDate.of(1995, Month.JUNE, 15);
        System.out.println("生日: " + birthday);

        LocalDate parsed = LocalDate.parse("2024-03-15"); // ISO 格式
        System.out.println("解析: " + parsed);

        // 获取字段
        System.out.println("年: " + today.getYear());
        System.out.println("月: " + today.getMonthValue());
        System.out.println("日: " + today.getDayOfMonth());
        System.out.println("星期: " + today.getDayOfWeek()); // FRIDAY
        System.out.println("年内第几天: " + today.getDayOfYear());

        // 日期运算（不可变，返回新对象）
        LocalDate tomorrow = today.plusDays(1);
        LocalDate nextWeek = today.plusWeeks(1);
        LocalDate nextMonth = today.plusMonths(1);
        LocalDate nextYear = today.plusYears(1);
        LocalDate lastMonth = today.minusMonths(1);

        System.out.println("明天: " + tomorrow);
        System.out.println("下周: " + nextWeek);
        System.out.println("下月: " + nextMonth);

        // 修改字段
        LocalDate firstDay = today.withDayOfMonth(1);
        LocalDate newYear = today.withMonth(1).withDayOfMonth(1);
        System.out.println("本月第一天: " + firstDay);

        // 比较
        System.out.println("今天在生日之后: " + today.isAfter(birthday));
        System.out.println("今天是否闰年: " + today.isLeapYear());

        // ===== LocalTime（时间）=====
        LocalTime now = LocalTime.now();
        LocalTime meeting = LocalTime.of(14, 30, 0);
        LocalTime parsedTime = LocalTime.parse("14:30:00");

        System.out.println("现在: " + now);
        System.out.println("会议时间: " + meeting);
        System.out.println("小时: " + now.getHour());
        System.out.println("分钟: " + now.getMinute());

        LocalTime later = now.plusHours(2).plusMinutes(30);
        System.out.println("2.5小时后: " + later);

        // ===== LocalDateTime（日期+时间）=====
        LocalDateTime dt = LocalDateTime.now();
        LocalDateTime specific = LocalDateTime.of(2024, 3, 15, 14, 30, 0);
        LocalDateTime combined = LocalDateTime.of(today, meeting);

        System.out.println("当前日期时间: " + dt);
        System.out.println("指定: " + specific);

        // ===== 格式化与解析 =====
        DateTimeFormatter formatter = DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm:ss");
        String formatted = dt.format(formatter);
        System.out.println("格式化: " + formatted); // 2024-03-15 14:30:00

        DateTimeFormatter cnFormatter = DateTimeFormatter.ofPattern("yyyy年MM月dd日 HH时mm分");
        System.out.println(dt.format(cnFormatter));

        LocalDateTime parsedDt = LocalDateTime.parse("2024-03-15 14:30:00", formatter);
        System.out.println("解析回: " + parsedDt);

        // 常用格式符
        // yyyy 四位年 MM 月 dd 日 HH 24小时 mm 分 ss 秒
        // EEE 星期缩写 EEEE 星期全名 MMM 月缩写 MMMM 月全名
        // SSS 毫秒 a 上午/下午

        // ===== Duration / Period（时间间隔）=====
        // Duration：基于时间（秒/纳秒）
        LocalDateTime start = LocalDateTime.of(2024, 1, 1, 0, 0);
        LocalDateTime end = LocalDateTime.of(2024, 1, 2, 12, 30);
        Duration duration = Duration.between(start, end);
        System.out.println("间隔天数: " + duration.toDays()); // 1
        System.out.println("间隔小时: " + duration.toHours()); // 36
        System.out.println("间隔分钟: " + duration.toMinutes()); // 2190

        // Period：基于日期（年/月/日）
        Period period = Period.between(birthday, today);
        System.out.println("年龄: " + period.getYears() + "岁"
            + period.getMonths() + "月" + period.getDays() + "天");

        // 计算两个日期相差天数
        long daysBetween = ChronoUnit.DAYS.between(birthday, today);
        System.out.println("出生天数: " + daysBetween);

        // ===== ZonedDateTime（带时区）=====
        ZonedDateTime zdt = ZonedDateTime.now(); // 默认时区
        ZonedDateTime shanghai = ZonedDateTime.now(ZoneId.of("Asia/Shanghai"));
        ZonedDateTime tokyo = ZonedDateTime.now(ZoneId.of("Asia/Tokyo"));
        ZonedDateTime newyork = ZonedDateTime.now(ZoneId.of("America/New_York"));

        System.out.println("上海: " + shanghai);
        System.out.println("东京: " + tokyo);
        System.out.println("纽约: " + newyork);

        // 时区转换
        ZonedDateTime converted = shanghai.withZoneSameInstant(ZoneId.of("America/New_York"));
        System.out.println("上海时间转纽约: " + converted);

        // ===== Instant（时间戳）=====
        Instant instant = Instant.now(); // UTC 时间戳
        System.out.println("时间戳: " + instant);
        System.out.println("毫秒: " + instant.toEpochMilli());
        System.out.println("秒: " + instant.getEpochSecond());

        // Instant 与 LocalDateTime 互转
        LocalDateTime fromInstant = LocalDateTime.ofInstant(instant, ZoneId.systemDefault());
        Instant toInstant = dt.atZone(ZoneId.systemDefault()).toInstant();

        // ===== TemporalAdjusters（时间调整器）=====
        LocalDate firstDayOfMonth = today.with(TemporalAdjusters.firstDayOfMonth());
        LocalDate lastDayOfMonth = today.with(TemporalAdjusters.lastDayOfMonth());
        LocalDate firstMonday = today.with(TemporalAdjusters.firstInMonth(DayOfWeek.MONDAY));
        LocalDate nextFriday = today.with(TemporalAdjusters.next(DayOfWeek.FRIDAY));

        System.out.println("本月第一天: " + firstDayOfMonth);
        System.out.println("本月最后一天: " + lastDayOfMonth);
        System.out.println("下周五: " + nextFriday);

        // ===== 与旧 API 互转 =====
        // java.util.Date -> Instant
        // Date date = new Date();
        // Instant inst = date.toInstant();

        // Instant -> Date
        // Date newDate = Date.from(Instant.now());

        // Calendar -> ZonedDateTime
        // Calendar cal = Calendar.getInstance();
        // ZonedDateTime zdt2 = cal.toInstant().atZone(cal.getTimeZone().toZoneId());
    }
}""",
                "tips": "java.time 所有类都是不可变的，修改操作返回新对象，线程安全；LocalDate/LocalTime/LocalDateTime 不带时区，ZonedDateTime 带时区；Duration 用于时间间隔（秒级），Period 用于日期间隔（年月日），不要混用；格式化用 DateTimeFormatter，是线程安全的（旧 SimpleDateFormat 不是）；解析字符串时格式必须严格匹配，否则抛 DateTimeParseException；时区用 ZoneId.of(\"洲/城市\")，不要用 ZoneId.of(\"GMT+8\") 这种偏移量（不处理夏令时）；Instant 是 UTC 时间戳，转换为本地时间需要指定时区；旧代码中的 Date/Calendar 可以用 toInstant() 互转；测试时用 Clock 固定时间，不要直接用 now()（难以测试）；TemporalAdjusters 提供丰富的日期调整逻辑，如本月最后一天、下周一等。",
            },
        ],
    }

_more2 = _more_modules2()
for _k, _v in _more2.items():
    if _k not in LANG_MODULES:
        LANG_MODULES[_k] = _v
del _more2, _more_modules2


def _more_modules3():
    return {
        "go": [
            {
                "name": "fmt — 格式化输入输出",
                "desc": "Go 语言标准格式化库，提供 Print/Println/Printf 输出、Scan/Scanln/Scanf 输入、Sprintf 字符串格式化、Errorf 错误格式化等功能，是 Go 程序最基础的库。",
                "functions": [
                    "fmt.Print(a...) — 输出（不自动换行）",
                    "fmt.Println(a...) — 输出并换行",
                    "fmt.Printf(format, a...) — 格式化输出",
                    "fmt.Sprintf(format, a...) — 格式化返回字符串",
                    "fmt.Fprintf(w, format, a...) — 输出到 io.Writer",
                    "fmt.Scan(&a...) — 从标准输入读取",
                    "fmt.Scanln(&a...) — 读取一行",
                    "fmt.Scanf(format, &a...) — 格式化读取",
                    "fmt.Errorf(format, a...) — 创建格式化错误",
                    "fmt.Sprintf(\"%v\", x) — 默认格式",
                    "fmt.Sprintf(\"%+v\", x) — 结构体带字段名",
                    "fmt.Sprintf(\"%#v\", x) — Go 语法表示",
                    "fmt.Sprintf(\"%T\", x) — 类型",
                    "fmt.Sprintf(\"%d\", x) — 十进制整数",
                    "fmt.Sprintf(\"%f\", x) — 浮点数",
                    "fmt.Sprintf(\"%s\", x) — 字符串",
                    "fmt.Sprintf(\"%t\", x) — 布尔值",
                    "fmt.Sprintf(\"%p\", x) — 指针地址",
                    "fmt.Sprintf(\"%.2f\", x) — 保留2位小数",
                    "fmt.Sprintf(\"%10d\", x) — 宽度10右对齐",
                    "fmt.Sprintf(\"%-10d\", x) — 宽度10左对齐",
                    "fmt.Sprintf(\"%05d\", x) — 补零到5位",
                ],
                "example": """package main

import (
    "fmt"
    "os"
)

type Person struct {
    Name string
    Age  int
}

func main() {
    // 基本输出
    fmt.Print("Hello, ")
    fmt.Println("World!")        // Hello, World!
    fmt.Println("一行", "两个", "值") // 一行 两个 值

    // 格式化输出
    name := "Alice"
    age := 25
    fmt.Printf("姓名: %s, 年龄: %d\\n", name, age)
    fmt.Printf("浮点数: %.2f\\n", 3.14159)
    fmt.Printf("布尔: %t\\n", true)

    // 格式化动词
    p := Person{Name: "Bob", Age: 30}
    fmt.Printf("%%v: %v\\n", p)    // %v: {Bob 30}
    fmt.Printf("%%+v: %+v\\n", p)  // %+v: {Name:Bob Age:30}
    fmt.Printf("%%#v: %#v\\n", p)  // %#v: main.Person{Name:"Bob", Age:30}
    fmt.Printf("%%T: %T\\n", p)    // %T: main.Person

    // Sprintf 返回字符串
    result := fmt.Sprintf("ID: %05d, Score: %.1f", 42, 95.5)
    fmt.Println(result) // ID: 00042, Score: 95.5

    // 宽度与对齐
    fmt.Printf("|%10s|\\n", "right")   // |     right|
    fmt.Printf("|%-10s|\\n", "left")    // |left      |
    fmt.Printf("|%010d|\\n", 123)       // |0000000123|

    // 输入
    var inputName string
    var inputAge int
    fmt.Print("输入姓名和年龄: ")
    fmt.Scanln(&inputName, &inputAge)
    fmt.Printf("你好, %s (%d岁)\\n", inputName, inputAge)

    // Fprintf 输出到 Writer
    fmt.Fprintf(os.Stderr, "这是错误输出\\n")

    // Errorf 创建错误
    err := fmt.Errorf("文件 %s 不存在 (错误码: %d)", "data.txt", 404)
    fmt.Println(err)

    // 字符串拼接（用 Sprintf 比 + 更灵活）
    items := []string{"apple", "banana", "cherry"}
    for i, item := range items {
        fmt.Printf("%d. %s\\n", i+1, item)
    }

    // 复杂格式化
    data := map[string]int{"a": 1, "b": 2}
    fmt.Printf("map: %v\\n", data)
    fmt.Printf("指针: %p\\n", &name)
}""",
                "tips": "Println 多个参数间自动加空格，Print 不加；格式化动词 %v 是万能格式，结构体用 %+v 显示字段名；%#v 输出 Go 语法表示，适合调试；Scan/Scanln 以空格分隔，读取整行用 bufio.Scanner；Errorf 支持 %w 包装错误（Go 1.13+），可用 errors.Is/As 判断；Fprintf 可输出到任意 io.Writer（文件、网络连接等）；浮点数格式化 %.2f 会四舍五入；宽度和精度可组合如 %10.2f。",
            },
            {
                "name": "net/http — HTTP 客户端与服务端",
                "desc": "Go 标准库 HTTP 包，提供 HTTP 客户端和服务端功能，支持 GET/POST 请求、文件上传、Cookie、Header、自定义 Transport、中间件、路由等，是 Go Web 开发的基础。",
                "functions": [
                    "http.Get(url) — 发送 GET 请求",
                    "http.Post(url, contentType, body) — 发送 POST 请求",
                    "http.PostForm(url, values) — 发送表单 POST",
                    "http.NewRequest(method, url, body) — 创建自定义请求",
                    "http.Client — HTTP 客户端（可配置超时/Transport）",
                    "client.Do(req) — 执行请求",
                    "http.ListenAndServe(addr, handler) — 启动 HTTP 服务",
                    "http.HandleFunc(pattern, handler) — 注册路由",
                    "http.Handle(pattern, handler) — 注册 Handler",
                    "http.ServeMux — 多路复用器（路由器）",
                    "http.ResponseWriter — 响应写入器",
                    "http.Request — 请求对象",
                    "r.URL.Query().Get(key) — 获取 URL 查询参数",
                    "r.FormValue(key) — 获取表单参数",
                    "r.Header.Get(key) — 获取请求头",
                    "r.Cookie(name) — 获取 Cookie",
                    "http.SetCookie(w, cookie) — 设置 Cookie",
                    "http.Error(w, msg, code) — 发送错误响应",
                    "http.Redirect(w, r, url, code) — 重定向",
                    "http.FileServer(root) — 静态文件服务",
                    "http.StripPrefix(prefix, handler) — 去除路径前缀",
                    "http.StatusOK / StatusNotFound — 状态码常量",
                    "ioutil.ReadAll(resp.Body) — 读取响应体",
                    "json.NewDecoder(r.Body).Decode(&v) — 解析 JSON 请求体",
                    "json.NewEncoder(w).Encode(v) — 写入 JSON 响应",
                    "context.WithTimeout — 请求超时控制",
                    "http.Transport — 自定义传输（连接池/代理/TLS）",
                ],
                "example": """package main

import (
    "bytes"
    "encoding/json"
    "fmt"
    "io"
    "log"
    "net/http"
    "net/url"
    "strings"
    "time"
)

// ===== 客户端 =====
func clientDemo() {
    // GET 请求
    resp, err := http.Get("https://api.example.com/users")
    if err != nil {
        log.Fatal(err)
    }
    defer resp.Body.Close()

    body, _ := io.ReadAll(resp.Body)
    fmt.Println("状态:", resp.Status)
    fmt.Println("响应:", string(body))

    // 带超时的客户端
    client := &http.Client{Timeout: 10 * time.Second}
    resp2, err := client.Get("https://api.example.com/data")
    if err != nil {
        log.Println("请求失败:", err)
        return
    }
    defer resp2.Body.Close()

    // POST JSON
    data := map[string]string{"name": "Alice", "email": "alice@example.com"}
    jsonData, _ := json.Marshal(data)
    resp3, err := http.Post("https://api.example.com/users",
        "application/json", bytes.NewBuffer(jsonData))
    if err != nil {
        log.Fatal(err)
    }
    defer resp3.Body.Close()

    // POST 表单
    form := url.Values{}
    form.Set("username", "alice")
    form.Set("password", "secret")
    resp4, err := http.PostForm("https://api.example.com/login", form)
    if err != nil {
        log.Fatal(err)
    }
    defer resp4.Body.Close()

    // 自定义请求（带 Header）
    req, err := http.NewRequest("GET", "https://api.example.com/protected", nil)
    if err != nil {
        log.Fatal(err)
    }
    req.Header.Set("Authorization", "Bearer your-token")
    req.Header.Set("Accept", "application/json")
    resp5, err := client.Do(req)
    if err != nil {
        log.Fatal(err)
    }
    defer resp5.Body.Close()

    // 解析 JSON 响应
    var result map[string]interface{}
    json.NewDecoder(resp5.Body).Decode(&result)
    fmt.Println(result)
}

// ===== 服务端 =====
type User struct {
    Name  string `json:"name"`
    Email string `json:"email"`
}

func helloHandler(w http.ResponseWriter, r *http.Request) {
    // 获取查询参数
    name := r.URL.Query().Get("name")
    if name == "" {
        name = "World"
    }
    fmt.Fprintf(w, "Hello, %s!", name)
}

func jsonHandler(w http.ResponseWriter, r *http.Request) {
    // 设置响应头
    w.Header().Set("Content-Type", "application/json")

    // 解析请求体
    var user User
    if err := json.NewDecoder(r.Body).Decode(&user); err != nil {
        http.Error(w, "无效的 JSON", http.StatusBadRequest)
        return
    }

    // 返回 JSON
    response := map[string]interface{}{
        "status":  "success",
        "message": fmt.Sprintf("用户 %s 创建成功", user.Name),
        "user":    user,
    }
    json.NewEncoder(w).Encode(response)
}

func formHandler(w http.ResponseWriter, r *http.Request) {
    if r.Method != http.MethodPost {
        http.Error(w, "只允许 POST", http.StatusMethodNotAllowed)
        return
    }
    r.ParseForm()
    username := r.FormValue("username")
    fmt.Fprintf(w, "你好, %s!", username)
}

// 中间件
func loggingMiddleware(next http.Handler) http.Handler {
    return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
        start := time.Now()
        log.Printf("开始: %s %s", r.Method, r.URL.Path)
        next.ServeHTTP(w, r)
        log.Printf("完成: %s %s (%v)", r.Method, r.URL.Path, time.Since(start))
    })
}

func authMiddleware(next http.Handler) http.Handler {
    return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
        token := r.Header.Get("Authorization")
        if token != "Bearer valid-token" {
            http.Error(w, "未授权", http.StatusUnauthorized)
            return
        }
        next.ServeHTTP(w, r)
    })
}

func serverDemo() {
    mux := http.NewServeMux()

    // 注册路由
    mux.HandleFunc("/", helloHandler)
    mux.HandleFunc("/api/user", jsonHandler)
    mux.HandleFunc("/login", formHandler)

    // 静态文件服务
    fs := http.FileServer(http.Dir("./static"))
    mux.Handle("/static/", http.StripPrefix("/static/", fs))

    // 应用中间件
    handler := loggingMiddleware(mux)

    // 受保护的路由
    protected := http.NewServeMux()
    protected.HandleFunc("/admin", func(w http.ResponseWriter, r *http.Request) {
        fmt.Fprintln(w, "管理员面板")
    })
    mux.Handle("/admin", authMiddleware(protected))

    // 启动服务
    fmt.Println("服务器启动在 :8080")
    log.Fatal(http.ListenAndServe(":8080", handler))

    // HTTPS 服务
    // http.ListenAndServeTLS(":443", "cert.pem", "key.pem", handler)
}

func main() {
    // clientDemo()
    serverDemo()
}""",
                "tips": "http.Get/Post 使用默认客户端（无超时！），生产环境必须用 &http.Client{Timeout: ...}；resp.Body 必须 Close（用 defer），否则连接泄漏；默认 Transport 有连接池，不要每次创建新 Client；POST JSON 用 bytes.NewBuffer(jsonData)，不要用 strings.NewReader；服务端 handler 中不要修改 r.Body 之外的请求字段；http.Error 会设置 Content-Type 为 text/plain；静态文件用 http.FileServer + StripPrefix；路由匹配默认 ServeMux 不支持路径参数，用 gorilla/mux 或 chi 等第三方库；中间件通过包装 Handler 实现；ListenAndServe 是阻塞的，错误时返回；生产环境用 graceful shutdown（Shutdown 方法）。",
            },
            {
                "name": "encoding/json — JSON 编解码",
                "desc": "Go 标准 JSON 编解码包，支持结构体与 JSON 互转、流式编解码、自定义 Marshal/Unmarshal、忽略字段、别名等，是 Go 处理 JSON 数据的核心库。",
                "functions": [
                    "json.Marshal(v) — 结构体转 JSON 字节",
                    "json.MarshalIndent(v, prefix, indent) — 格式化输出",
                    "json.Unmarshal(data, &v) — JSON 字节转结构体",
                    "json.NewEncoder(w).Encode(v) — 流式编码到 Writer",
                    "json.NewDecoder(r).Decode(&v) — 从 Reader 流式解码",
                    "json.Valid(data) — 检查 JSON 是否合法",
                    "json.RawMessage — 延迟解析的原始 JSON",
                    "json.Number — 数字类型（避免精度丢失）",
                    "结构体标签 `json:\"name\"` — 指定 JSON 字段名",
                    "`json:\"-\"` — 忽略字段",
                    "`json:\"name,omitempty\"` — 空值时忽略",
                    "`json:\",string\"` — 序列化为字符串",
                    "json.Marshaler / json.Unmarshaler — 自定义编解码接口",
                    "Decoder.UseNumber() — 数字解析为 json.Number",
                    "Decoder.DisallowUnknownFields() — 不允许未知字段",
                    "json.NewDecoder — 支持流式读取大文件",
                ],
                "example": """package main

import (
    "bytes"
    "encoding/json"
    "fmt"
    "log"
    "os"
    "strings"
)

// 结构体定义（字段名首字母大写才能被序列化）
type User struct {
    ID       int      `json:"id"`
    Name     string   `json:"name"`
    Email    string   `json:"email"`
    Age      int      `json:"age,omitempty"` // 空值忽略
    Password string   `json:"-"`              // 永远忽略
    Tags     []string `json:"tags,omitempty"`
    Active   bool     `json:"active"`
}

type Address struct {
    City    string `json:"city"`
    Country string `json:"country"`
}

type Person struct {
    Name    string  `json:"name"`
    Age     int     `json:"age"`
    Address Address `json:"address"` // 嵌套结构体
}

func main() {
    // ===== Marshal：结构体 -> JSON =====
    user := User{
        ID:     1,
        Name:   "Alice",
        Email:  "alice@example.com",
        Age:    25,
        Active: true,
        Tags:   []string{"admin", "editor"},
    }

    data, err := json.Marshal(user)
    if err != nil {
        log.Fatal(err)
    }
    fmt.Println(string(data))
    // {"id":1,"name":"Alice","email":"alice@example.com","age":25,"tags":["admin","editor"],"active":true}

    // 格式化输出
    pretty, _ := json.MarshalIndent(user, "", "  ")
    fmt.Println(string(pretty))

    // omitempty 效果：Age=0 时不输出
    user2 := User{ID: 2, Name: "Bob", Email: "bob@example.com", Active: false}
    data2, _ := json.Marshal(user2)
    fmt.Println(string(data2))
    // {"id":2,"name":"Bob","email":"bob@example.com","active":false}

    // ===== Unmarshal：JSON -> 结构体 =====
    jsonStr := `{"id":3,"name":"Charlie","email":"charlie@example.com","age":30,"active":true}`
    var user3 User
    err = json.Unmarshal([]byte(jsonStr), &user3)
    if err != nil {
        log.Fatal(err)
    }
    fmt.Printf("%+v\\n", user3)

    // 解析到 map（未知结构时）
    var result map[string]interface{}
    json.Unmarshal([]byte(jsonStr), &result)
    fmt.Println("name:", result["name"])
    fmt.Println("age:", result["age"]) // 数字默认是 float64

    // ===== 流式编解码（大文件/网络）=====
    // Encoder：写入到 Writer
    var buf bytes.Buffer
    encoder := json.NewEncoder(&buf)
    encoder.SetIndent("", "  ")
    encoder.Encode(user)
    fmt.Println(buf.String())

    // Decoder：从 Reader 读取
    reader := strings.NewReader(jsonStr)
    decoder := json.NewDecoder(reader)
    var user4 User
    decoder.Decode(&user4)
    fmt.Printf("流式解码: %+v\\n", user4)

    // 解码多个 JSON 对象（流式）
    multiJSON := `{"name":"a"}{"name":"b"}{"name":"c"}`
    dec := json.NewDecoder(strings.NewReader(multiJSON))
    for {
        var item map[string]string
        if err := dec.Decode(&item); err != nil {
            break
        }
        fmt.Println("流式多条:", item["name"])
    }

    // ===== 数字精度（UseNumber）=====
    bigNumJSON := `{"value": 12345678901234567890}`
    var normal map[string]interface{}
    json.Unmarshal([]byte(bigNumJSON), &normal)
    fmt.Printf("普通解析: %v (类型: %T)\\n", normal["value"], normal["value"])
    // 可能丢失精度

    dec2 := json.NewDecoder(strings.NewReader(bigNumJSON))
    dec2.UseNumber()
    var precise map[string]json.Number
    dec2.Decode(&precise)
    fmt.Printf("精确解析: %s\\n", precise["value"])
    // json.Number 可以转 int64 或 float64
    n, _ := precise["value"].Int64()
    fmt.Println("转 int64:", n)

    // ===== RawMessage：延迟解析 =====
    type Envelope struct {
        Type string          `json:"type"`
        Data json.RawMessage `json:"data"` // 先不解析
    }
    rawJSON := `{"type":"user","data":{"id":1,"name":"Alice"}}`
    var env Envelope
    json.Unmarshal([]byte(rawJSON), &env)
    fmt.Println("类型:", env.Type)
    // 根据类型再解析 Data
    if env.Type == "user" {
        var u User
        json.Unmarshal(env.Data, &u)
        fmt.Printf("延迟解析用户: %+v\\n", u)
    }

    // ===== 自定义编解码 =====
    type Date struct {
        Day   int
        Month int
        Year  int
    }
    // 实现 MarshalJSON 方法
    // func (d Date) MarshalJSON() ([]byte, error) {
    //     return json.Marshal(fmt.Sprintf("%04d-%02d-%02d", d.Year, d.Month, d.Day))
    // }

    // ===== 数组/切片 =====
    users := []User{
        {ID: 1, Name: "Alice", Email: "a@example.com", Active: true},
        {ID: 2, Name: "Bob", Email: "b@example.com", Active: true},
    }
    usersJSON, _ := json.Marshal(users)
    fmt.Println("数组:", string(usersJSON))

    var decodedUsers []User
    json.Unmarshal(usersJSON, &decodedUsers)
    fmt.Printf("解码数组: %d 个用户\\n", len(decodedUsers))

    // ===== 写入/读取文件 =====
    file, _ := os.Create("user.json")
    json.NewEncoder(file).Encode(user)
    file.Close()

    file2, _ := os.Open("user.json")
    var loaded User
    json.NewDecoder(file2).Decode(&loaded)
    file2.Close()
    fmt.Printf("从文件加载: %+v\\n", loaded)
}""",
                "tips": "结构体字段必须首字母大写（导出）才能被序列化，否则被忽略；用 json tag 指定字段名、omitempty、- 等；数字默认解析为 float64，大整数会丢失精度，用 Decoder.UseNumber() 或定义为 json.Number；Marshal 不返回错误时一定是合法 JSON；Unmarshal 遇到未知字段默认忽略，用 DisallowUnknownFields() 严格模式；嵌套结构体自动递归序列化；指针字段为 nil 时输出 null（除非 omitempty）；自定义编解码实现 json.Marshaler/json.Unmarshaler 接口；流式编解码适合大文件和网络传输，避免一次性读入内存；time.Time 默认序列化为 RFC3339 格式字符串。",
            },
            {
                "name": "sync — 同步原语与并发控制",
                "desc": "Go 同步包提供互斥锁、读写锁、等待组、单次执行、Map 等并发原语，配合 goroutine 和 channel 使用，是 Go 并发编程的重要工具。",
                "functions": [
                    "sync.Mutex — 互斥锁",
                    "mu.Lock() / mu.Unlock() — 加锁/解锁",
                    "sync.RWMutex — 读写锁",
                    "rw.RLock() / rw.RUnlock() — 读锁",
                    "rw.Lock() / rw.Unlock() — 写锁",
                    "sync.WaitGroup — 等待组",
                    "wg.Add(n) — 增加计数",
                    "wg.Done() — 计数减1",
                    "wg.Wait() — 等待计数归零",
                    "sync.Once — 单次执行",
                    "once.Do(f) — 只执行一次",
                    "sync.Map — 并发安全 Map",
                    "m.Store(k, v) / Load(k) / LoadOrStore / Delete / Range",
                    "sync.Pool — 对象池",
                    "pool.Get() / pool.Put(x)",
                    "sync.Cond — 条件变量",
                    "cond.Wait() / Signal() / Broadcast()",
                    "atomic — 原子操作包（sync/atomic）",
                    "atomic.AddInt64 / LoadInt64 / StoreInt64 / CompareAndSwapInt64",
                    "channel — Go 内置通道（非 sync 包）",
                    "chan T / make(chan T, buffer) — 创建通道",
                    "ch <- x / x := <-ch — 发送/接收",
                    "close(ch) — 关闭通道",
                    "select — 多路复用",
                    "for-range 遍历通道",
                    "context — 上下文取消/超时（context 包）",
                ],
                "example": """package main

import (
    "fmt"
    "sync"
    "sync/atomic"
    "time"
)

// ===== Mutex 互斥锁 =====
type Counter struct {
    mu    sync.Mutex
    count int
}

func (c *Counter) Increment() {
    c.mu.Lock()
    defer c.mu.Unlock() // 确保解锁
    c.count++
}

func (c *Counter) Value() int {
    c.mu.Lock()
    defer c.mu.Unlock()
    return c.count
}

// ===== RWMutex 读写锁（读多写少）=====
type Config struct {
    mu    sync.RWMutex
    data  map[string]string
}

func (c *Config) Get(key string) string {
    c.mu.RLock() // 读锁（多个 goroutine 可同时读）
    defer c.mu.RUnlock()
    return c.data[key]
}

func (c *Config) Set(key, value string) {
    c.mu.Lock() // 写锁（独占）
    defer c.mu.Unlock()
    c.data[key] = value
}

// ===== WaitGroup 等待多个 goroutine =====
func waitGroupDemo() {
    var wg sync.WaitGroup
    var counter int64

    for i := 0; i < 100; i++ {
        wg.Add(1) // 启动前增加计数
        go func(n int) {
            defer wg.Done() // 完成后减1
            atomic.AddInt64(&counter, 1) // 原子操作
        }(i)
    }

    wg.Wait() // 等待所有 goroutine 完成
    fmt.Println("WaitGroup 计数:", counter) // 100
}

// ===== sync.Once 单次执行 =====
type Singleton struct {
    once sync.Once
    instance *Config
}

func (s *Singleton) Get() *Config {
    s.once.Do(func() {
        // 只执行一次，线程安全
        s.instance = &Config{data: make(map[string]string)}
        fmt.Println("Singleton 初始化")
    })
    return s.instance
}

// ===== sync.Map 并发安全 Map =====
func syncMapDemo() {
    var m sync.Map

    // 写入
    m.Store("key1", "value1")
    m.Store("key2", "value2")

    // 读取
    if v, ok := m.Load("key1"); ok {
        fmt.Println("syncMap key1:", v)
    }

    // LoadOrStore：存在则返回已有，不存在则存储
    actual, loaded := m.LoadOrStore("key1", "new-value")
    fmt.Println("LoadOrStore:", actual, "已存在:", loaded)

    // 删除
    m.Delete("key2")

    // 遍历
    m.Range(func(key, value interface{}) bool {
        fmt.Printf("  %s = %s\\n", key, value)
        return true // 返回 false 停止遍历
    })
}

// ===== sync.Pool 对象池 =====
func poolDemo() {
    pool := &sync.Pool{
        New: func() interface{} {
            fmt.Println("创建新对象")
            return make([]byte, 1024)
        },
    }

    // 获取对象
    obj := pool.Get().([]byte)
    fmt.Printf("获取对象: %d 字节\\n", len(obj))

    // 使用后归还
    pool.Put(obj)
    fmt.Println("归还对象")

    // 再次获取（可能复用之前的对象）
    obj2 := pool.Get().([]byte)
    fmt.Printf("再次获取: %d 字节\\n", len(obj2))
}

// ===== Channel 通道 =====
func channelDemo() {
    // 无缓冲通道（同步）
    ch := make(chan string)
    go func() {
        ch <- "Hello from goroutine" // 发送
    }()
    msg := <-ch // 接收（阻塞直到有数据）
    fmt.Println("无缓冲通道:", msg)

    // 有缓冲通道
    buffered := make(chan int, 3)
    buffered <- 1
    buffered <- 2
    buffered <- 3
    fmt.Println("缓冲通道大小:", len(buffered)) // 3
    close(buffered) // 关闭通道

    // for-range 遍历通道（通道关闭后自动结束）
    for v := range buffered {
        fmt.Print(v, " ")
    }
    fmt.Println()

    // select 多路复用
    ch1 := make(chan string)
    ch2 := make(chan string)
    go func() { time.Sleep(100 * time.Millisecond); ch1 <- "from ch1" }()
    go func() { time.Sleep(50 * time.Millisecond); ch2 <- "from ch2" }()

    for i := 0; i < 2; i++ {
        select {
        case msg1 := <-ch1:
            fmt.Println("收到:", msg1)
        case msg2 := <-ch2:
            fmt.Println("收到:", msg2)
        case <-time.After(200 * time.Millisecond):
            fmt.Println("超时")
        }
    }

    // 非阻塞接收（default 分支）
    select {
    case v := <-ch1:
        fmt.Println(v)
    default:
        fmt.Println("无数据可用")
    }

    // 生产者消费者模式
    jobs := make(chan int, 10)
    results := make(chan int, 10)

    // 3个消费者
    for w := 1; w <= 3; w++ {
        go func(id int) {
            for job := range jobs {
                fmt.Printf("Worker %d 处理 job %d\\n", id, job)
                results <- job * 2
            }
        }(w)
    }

    // 生产者发送5个任务
    for j := 1; j <= 5; j++ {
        jobs <- j
    }
    close(jobs)

    // 收集结果
    for r := 1; r <= 5; r++ {
        fmt.Println("结果:", <-results)
    }
}

// ===== 原子操作 =====
func atomicDemo() {
    var counter int64
    var wg sync.WaitGroup

    for i := 0; i < 1000; i++ {
        wg.Add(1)
        go func() {
            defer wg.Done()
            atomic.AddInt64(&counter, 1) // 原子自增
        }()
    }
    wg.Wait()
    fmt.Println("原子计数:", counter) // 1000

    // CompareAndSwap（CAS）
    var value int64 = 10
    swapped := atomic.CompareAndSwapInt64(&value, 10, 20) // 如果当前是10则改为20
    fmt.Println("CAS 成功:", swapped, "值:", value)

    // Load / Store
    atomic.StoreInt64(&value, 100)
    fmt.Println("Load:", atomic.LoadInt64(&value))
}

// ===== context 上下文 =====
// func contextDemo() {
//     ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
//     defer cancel()
//
//     go func() {
//         select {
//         case <-time.After(3 * time.Second):
//             fmt.Println("任务完成")
//         case <-ctx.Done():
//             fmt.Println("任务取消:", ctx.Err())
//         }
//     }()
//     time.Sleep(3 * time.Second)
// }

func main() {
    fmt.Println("=== Mutex ===")
    c := &Counter{}
    var wg sync.WaitGroup
    for i := 0; i < 1000; i++ {
        wg.Add(1)
        go func() { defer wg.Done(); c.Increment() }()
    }
    wg.Wait()
    fmt.Println("Mutex 计数:", c.Value()) // 1000

    fmt.Println("=== WaitGroup ===")
    waitGroupDemo()

    fmt.Println("=== sync.Once ===")
    s := &Singleton{}
    s.Get()
    s.Get() // 不会再次初始化

    fmt.Println("=== sync.Map ===")
    syncMapDemo()

    fmt.Println("=== sync.Pool ===")
    poolDemo()

    fmt.Println("=== Channel ===")
    channelDemo()

    fmt.Println("=== Atomic ===")
    atomicDemo()
}""",
                "tips": "Mutex 不可复制（值传递会导致锁失效），用指针或嵌入结构体；Unlock 必须在 Lock 之后调用，否则 panic；用 defer Unlock 确保锁释放；RWMutex 适合读多写少，读锁可共享，写锁独占；WaitGroup 的 Add 必须在 goroutine 启动前调用，Done 在 goroutine 内调用；sync.Once 是线程安全的单例模式首选；sync.Map 适合读多写少且 key 集合稳定的场景，普通场景用 map+Mutex；sync.Pool 用于减少 GC 压力，对象随时可能被回收，不要存重要状态；Channel 是 Go 并发的首选，遵循\"不要通过共享内存通信，而要通过通信共享内存\"；无缓冲通道是同步的，有缓冲通道是异步的；close 只能关闭发送方，接收方 close 会 panic；select 多个 case 就绪时随机选择；context 用于传递取消信号和超时，是函数第一个参数；原子操作适合简单计数器，复杂状态用 Mutex。",
            },
            {
                "name": "os / io — 系统与IO操作",
                "desc": "os 包提供平台无关的操作系统接口（文件、目录、环境变量、进程、信号等）；io 包提供 IO 原语接口（Reader/Writer/Closer 等）和工具函数，是 Go 文件和 IO 操作的基础。",
                "functions": [
                    "os.Open(name) — 打开文件（只读）",
                    "os.Create(name) — 创建/截断文件（读写）",
                    "os.OpenFile(name, flag, perm) — 自定义模式打开",
                    "os.ReadFile(name) — 读取整个文件（Go 1.16+）",
                    "os.WriteFile(name, data, perm) — 写入整个文件",
                    "os.Mkdir(name, perm) / MkdirAll — 创建目录",
                    "os.Remove(name) / RemoveAll — 删除文件/目录",
                    "os.Rename(old, new) — 重命名/移动",
                    "os.Stat(name) — 获取文件信息",
                    "os.IsNotExist(err) / IsExist — 判断错误类型",
                    "os.Getenv(key) / Setenv / Unsetenv — 环境变量",
                    "os.Args — 命令行参数",
                    "os.Exit(code) — 退出程序",
                    "os.Getwd() / Chdir — 工作目录",
                    "os.UserHomeDir() — 用户主目录",
                    "os.TempDir() — 临时目录",
                    "os.Stdin / Stdout / Stderr — 标准流",
                    "io.Reader / io.Writer — 核心接口",
                    "io.Copy(dst, src) — 复制数据",
                    "io.ReadAll(r) — 读取全部",
                    "io.LimitReader(r, n) — 限制读取量",
                    "io.TeeReader(r, w) — 读取同时写入",
                    "io.MultiReader / MultiWriter — 多输入/输出",
                    "io.Pipe() — 管道",
                    "io.EOF — 文件结束错误",
                    "bufio.Scanner / Reader / Writer — 缓冲IO",
                    "filepath — 路径处理（path/filepath）",
                ],
                "example": """package main

import (
    "bufio"
    "fmt"
    "io"
    "os"
    "path/filepath"
    "strings"
)

func main() {
    // ===== 简单读写（Go 1.16+）=====
    // 写入文件
    content := []byte("Hello, World!\\n第二行\\n第三行\\n")
    err := os.WriteFile("test.txt", content, 0644)
    if err != nil {
        fmt.Println("写入失败:", err)
    }

    // 读取整个文件
    data, err := os.ReadFile("test.txt")
    if err != nil {
        fmt.Println("读取失败:", err)
    }
    fmt.Println("文件内容:", string(data))

    // ===== 传统文件操作 =====
    // 创建并写入
    file, err := os.Create("output.txt")
    if err != nil {
        fmt.Println("创建失败:", err)
        return
    }
    defer file.Close()

    file.WriteString("第一行\\n")
    file.Write([]byte("第二行\\n"))
    fmt.Fprintf(file, "格式化行: %d\\n", 42)

    // 打开读取
    file2, err := os.Open("output.txt")
    if err != nil {
        fmt.Println("打开失败:", err)
        return
    }
    defer file2.Close()

    // 读取全部
    all, _ := io.ReadAll(file2)
    fmt.Println("全部内容:", string(all))

    // 按行读取（bufio）
    file3, _ := os.Open("output.txt")
    defer file3.Close()
    scanner := bufio.NewScanner(file3)
    for scanner.Scan() {
        fmt.Println("行:", scanner.Text())
    }
    if err := scanner.Err(); err != nil {
        fmt.Println("扫描错误:", err)
    }

    // OpenFile 自定义模式
    // os.O_RDONLY 只读 O_WRONLY 只写 O_RDWR 读写
    // os.O_APPEND 追加 O_CREATE 创建 O_TRUNC 截断 O_EXCL 排他
    f, err := os.OpenFile("log.txt", os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0644)
    if err == nil {
        f.WriteString("追加日志\\n")
        f.Close()
    }

    // ===== 目录操作 =====
    // 创建目录
    os.Mkdir("mydir", 0755)
    os.MkdirAll("path/to/dir", 0755) // 递归创建

    // 列出目录
    entries, err := os.ReadDir(".")
    if err == nil {
        for _, entry := range entries {
            info, _ := entry.Info()
            fmt.Printf("  %s  %d bytes  isDir=%v\\n",
                entry.Name(), info.Size(), entry.IsDir())
        }
    }

    // 重命名/移动
    os.Rename("test.txt", "renamed.txt")

    // 删除
    os.Remove("renamed.txt")
    os.RemoveAll("mydir") // 递归删除

    // ===== 文件信息 =====
    info, err := os.Stat("output.txt")
    if err == nil {
        fmt.Println("文件名:", info.Name())
        fmt.Println("大小:", info.Size(), "bytes")
        fmt.Println("权限:", info.Mode())
        fmt.Println("修改时间:", info.ModTime())
        fmt.Println("是目录:", info.IsDir())
    }

    // 判断文件是否存在
    if _, err := os.Stat("nonexistent.txt"); os.IsNotExist(err) {
        fmt.Println("文件不存在")
    }

    // ===== 环境变量 =====
    os.Setenv("MY_VAR", "hello")
    fmt.Println("环境变量:", os.Getenv("MY_VAR"))
    fmt.Println("PATH:", os.Getenv("PATH")[:50], "...")

    // 命令行参数
    fmt.Println("程序名:", os.Args[0])
    if len(os.Args) > 1 {
        fmt.Println("参数:", os.Args[1:])
    }

    // 工作目录
    wd, _ := os.Getwd()
    fmt.Println("工作目录:", wd)

    // 用户主目录
    home, _ := os.UserHomeDir()
    fmt.Println("主目录:", home)

    // 临时目录
    fmt.Println("临时目录:", os.TempDir())

    // ===== io 包工具 =====
    // io.Copy 复制
    src, _ := os.Open("output.txt")
    dst, _ := os.Create("copy.txt")
    written, _ := io.Copy(dst, src)
    src.Close()
    dst.Close()
    fmt.Println("复制字节数:", written)

    // io.LimitReader 限制读取
    file4, _ := os.Open("output.txt")
    limited := io.LimitReader(file4, 10) // 只读10字节
    limitedData, _ := io.ReadAll(limited)
    fmt.Println("限制读取:", string(limitedData))
    file4.Close()

    // io.TeeReader 读取同时写入
    file5, _ := os.Open("output.txt")
    teeFile, _ := os.Create("tee.txt")
    teeReader := io.TeeReader(file5, teeFile)
    io.ReadAll(teeReader) // 读取的同时写入 tee.txt
    file5.Close()
    teeFile.Close()

    // io.MultiWriter 同时写入多个目标
    mw := io.MultiWriter(os.Stdout, &strings.Builder{})
    fmt.Fprintln(mw, "同时输出到控制台和字符串")

    // ===== 路径处理 =====
    path := filepath.Join("dir", "subdir", "file.txt")
    fmt.Println("拼接路径:", path)
    fmt.Println("目录:", filepath.Dir(path))
    fmt.Println("文件名:", filepath.Base(path))
    fmt.Println("扩展名:", filepath.Ext(path))
    fmt.Println("绝对路径:", filepath.IsAbs(path))

    // 遍历目录树
    filepath.Walk(".", func(path string, info os.FileInfo, err error) error {
        if err != nil {
            return err
        }
        if !info.IsDir() && strings.HasSuffix(path, ".txt") {
            fmt.Println("找到 txt:", path)
        }
        return nil
    })

    // ===== 标准输入 =====
    fmt.Print("输入内容: ")
    reader := bufio.NewReader(os.Stdin)
    input, _ := reader.ReadString('\\n')
    fmt.Println("你输入了:", strings.TrimSpace(input))

    // 清理
    os.Remove("copy.txt")
    os.Remove("tee.txt")
    os.Remove("log.txt")
    os.Remove("output.txt")
    os.RemoveAll("path")
}""",
                "tips": "os.ReadFile/WriteFile 是 Go 1.16+ 推荐的简单读写方式，但会一次性读入内存，大文件用流式；文件操作必须检查错误，defer Close()；OpenFile 的 flag 用位或组合，权限用八进制（0644/0755）；os.IsNotExist/IsExist 是判断错误类型的标准方式，不要用字符串比较；Mkdir 只创建一级，MkdirAll 递归创建；RemoveAll 递归删除目录树，慎用；环境变量用 Getenv/Setenv，LookupEnv 可判断是否存在；io.Copy 是复制数据的高效方式，内部有缓冲；bufio.Scanner 默认按行分割，长行需要 SetBuffer 增大；filepath.Join 跨平台路径拼接，不要手动拼字符串；filepath.Walk 遍历目录树，返回 error 可跳过；标准输入读取用 bufio.NewReader 或 Scanner；临时文件用 os.CreateTemp，用完删除；权限位 0644 = rw-r--r--，0755 = rwxr-xr-x。",
            },
        ],
    }

_more3 = _more_modules3()
for _k, _v in _more3.items():
    if _k not in LANG_MODULES:
        LANG_MODULES[_k] = _v
del _more3, _more_modules3


def _more_modules4():
    return {
        "rust": [
            {
                "name": "std::collections — 集合类型",
                "desc": "Rust 标准库集合模块，提供 HashMap、HashSet、VecDeque、BTreeMap、BTreeSet、BinaryHeap 等集合类型，是 Rust 数据结构的核心。",
                "functions": [
                    "Vec<T> — 动态数组（最常用）",
                    "vec![...] — 宏创建向量",
                    "v.push(x) / pop() — 末尾增删",
                    "v.insert(i, x) / remove(i) — 指定位置增删",
                    "v.len() / is_empty() / capacity()",
                    "v.get(i) — 返回 Option<&T>（安全访问）",
                    "v[i] — 索引访问（越界 panic）",
                    "v.iter() / iter_mut() / into_iter() — 迭代",
                    "v.sort() / sort_by / sort_by_key",
                    "v.contains(&x) / binary_search",
                    "HashMap<K,V> — 哈希表",
                    "map.insert(k,v) / get(k) / remove(k)",
                    "map.entry(k).or_insert(v) — 安全插入",
                    "map.contains_key(k) / len() / iter()",
                    "HashSet<T> — 哈希集合",
                    "set.insert(x) / contains(x) / remove(x)",
                    "set.union / intersection / difference",
                    "VecDeque<T> — 双端队列",
                    "deque.push_front / push_back / pop_front / pop_back",
                    "BTreeMap<K,V> — 有序映射（B树）",
                    "BTreeSet<T> — 有序集合",
                    "BinaryHeap<T> — 优先队列（大顶堆）",
                    "heap.push / pop / peek",
                    "Iterator trait — 迭代器 trait",
                    "collect() — 收集迭代器为集合",
                    "extend() — 扩展集合",
                    "drain() — 排空集合",
                ],
                "example": """use std::collections::{HashMap, HashSet, VecDeque, BTreeMap, BinaryHeap};

fn main() {
    // ===== Vec 动态数组 =====
    let mut v: Vec<i32> = Vec::new();
    v.push(1);
    v.push(2);
    v.push(3);

    let mut v2 = vec![1, 2, 3, 4, 5]; // 宏创建
    let v3 = vec![0; 10]; // 10个0

    // 访问
    println!("第一个: {}", v[0]); // 1
    match v.get(10) { // 安全访问，越界返回 None
        Some(val) => println!("值: {}", val),
        None => println!("越界"),
    }

    // 修改
    v2[0] = 100;
    v2.insert(1, 200); // 在索引1插入
    v2.remove(0);       // 删除索引0
    let last = v2.pop(); // 弹出末尾 Option<i32>

    // 遍历
    for x in &v {
        println!("{}", x);
    }
    for x in &mut v2 {
        *x *= 2; // 可变引用需要解引用
    }

    // 迭代器方法
    let sum: i32 = v.iter().sum();
    let doubled: Vec<i32> = v.iter().map(|x| x * 2).collect();
    let filtered: Vec<&i32> = v.iter().filter(|x| **x > 1).collect();
    let max = v.iter().max();
    let sorted = {
        let mut s = v.clone();
        s.sort();
        s
    };

    // 切片
    let slice = &v[1..3]; // [2, 3]

    // ===== HashMap =====
    let mut scores: HashMap<String, i32> = HashMap::new();
    scores.insert(String::from("Alice"), 95);
    scores.insert(String::from("Bob"), 87);

    // 访问
    println!("Alice: {:?}", scores.get("Alice")); // Some(95)
    println!("Eve: {:?}", scores.get("Eve"));     // None

    // entry API（安全插入/更新）
    scores.entry(String::from("Charlie")).or_insert(92);
    scores.entry(String::from("Alice")).and_modify(|s| *s += 5);

    // 遍历
    for (name, score) in &scores {
        println!("{}: {}", name, score);
    }

    // 统计词频
    let text = "apple banana apple orange banana apple";
    let mut freq: HashMap<&str, i32> = HashMap::new();
    for word in text.split_whitespace() {
        *freq.entry(word).or_insert(0) += 1;
    }
    println!("词频: {:?}", freq);

    // ===== HashSet =====
    let mut set: HashSet<i32> = HashSet::new();
    set.insert(1);
    set.insert(2);
    set.insert(1); // 重复，返回 false

    println!("包含1: {}", set.contains(&1));
    set.remove(&2);

    // 集合运算
    let a: HashSet<i32> = [1, 2, 3].iter().cloned().collect();
    let b: HashSet<i32> = [2, 3, 4].iter().cloned().collect();
    println!("并集: {:?}", a.union(&b).collect::<Vec<_>>());
    println!("交集: {:?}", a.intersection(&b).collect::<Vec<_>>());
    println!("差集: {:?}", a.difference(&b).collect::<Vec<_>>());

    // 去重
    let nums = vec![1, 2, 2, 3, 3, 3, 4];
    let unique: HashSet<_> = nums.iter().collect();
    println!("去重: {} 个", unique.len());

    // ===== VecDeque 双端队列 =====
    let mut deque: VecDeque<i32> = VecDeque::new();
    deque.push_back(1);
    deque.push_back(2);
    deque.push_front(0); // [0, 1, 2]
    let front = deque.pop_front(); // Some(0)
    let back = deque.pop_back();   // Some(2)

    // 作为队列使用
    let mut queue: VecDeque<i32> = VecDeque::new();
    queue.push_back(1);
    queue.push_back(2);
    if let Some(x) = queue.pop_front() {
        println!("出队: {}", x); // 1
    }

    // 作为栈使用
    let mut stack: VecDeque<i32> = VecDeque::new();
    stack.push_back(1);
    stack.push_back(2);
    if let Some(x) = stack.pop_back() {
        println!("出栈: {}", x); // 2
    }

    // ===== BTreeMap 有序映射 =====
    let mut btree: BTreeMap<i32, &str> = BTreeMap::new();
    btree.insert(3, "three");
    btree.insert(1, "one");
    btree.insert(2, "two");

    // 按 key 有序遍历
    for (k, v) in &btree {
        println!("{}: {}", k, v); // 1:one, 2:two, 3:three
    }

    // 范围查询
    for (k, v) in btree.range(1..=2) {
        println!("范围 {}: {}", k, v);
    }

    // ===== BinaryHeap 优先队列 =====
    let mut heap: BinaryHeap<i32> = BinaryHeap::new();
    heap.push(5);
    heap.push(1);
    heap.push(3);

    // 大顶堆：弹出顺序 5, 3, 1
    while let Some(max) = heap.pop() {
        println!("堆顶: {}", max);
    }

    // 小顶堆（用 Reverse 包装）
    use std::cmp::Reverse;
    let mut min_heap: BinaryHeap<Reverse<i32>> = BinaryHeap::new();
    min_heap.push(Reverse(5));
    min_heap.push(Reverse(1));
    min_heap.push(Reverse(3));
    while let Some(Reverse(min)) = min_heap.pop() {
        println!("小顶堆: {}", min); // 1, 3, 5
    }

    // ===== collect 收集 =====
    let v: Vec<i32> = (1..=5).collect();
    let s: HashSet<i32> = (1..=5).collect();
    let m: HashMap<i32, i32> = (1..=5).map(|x| (x, x * x)).collect();

    println!("完成");
}""",
                "tips": "Vec 是 Rust 最常用的集合，底层是连续数组；索引访问 v[i] 越界会 panic，安全访问用 v.get(i) 返回 Option；iter() 借用，into_iter() 转移所有权，iter_mut() 可变借用；collect() 需要指定目标类型（类型推断或显式标注）；HashMap 默认用 SipHash 防哈希碰撞攻击，性能敏感可用 rustc_hash::FxHashMap；entry API 是 Rust 的特色，or_insert/and_modify/or_insert_with 避免重复查找；HashSet 本质是 HashMap<T, ()>；VecDeque 用环形缓冲区实现，头尾增删 O(1)；BTreeMap/BTreeSet 是有序的，支持范围查询；BinaryHeap 默认大顶堆，小顶堆用 Reverse 包装；集合类型都实现了 IntoIterator，可直接 for 循环；drain() 可以排空集合并获取迭代器，原集合变空。",
            },
            {
                "name": "std::fs / std::io — 文件与IO",
                "desc": "std::fs 提供文件系统操作（读写文件、目录、元数据等）；std::io 提供 IO trait（Read/Write/Seek/BufRead）和工具类型，是 Rust 文件和 IO 操作的基础。",
                "functions": [
                    "fs::read_to_string(path) — 读取文件为字符串",
                    "fs::read(path) — 读取文件为字节 Vec",
                    "fs::write(path, contents) — 写入文件",
                    "fs::File::open(path) — 打开文件（只读）",
                    "fs::File::create(path) — 创建文件（只写，截断）",
                    "OpenOptions::new().read(true).write(true).open()",
                    "file.read_to_string(&mut s) / read(&mut buf)",
                    "file.write_all(&buf) / write_fmt(format_args!)",
                    "io::Read trait — 读取 trait",
                    "io::Write trait — 写入 trait",
                    "io::BufReader::new(file) — 缓冲读取",
                    "io::BufWriter::new(file) — 缓冲写入",
                    "BufReader::lines() — 按行迭代",
                    "fs::metadata(path) — 文件元数据",
                    "fs::create_dir / create_dir_all — 创建目录",
                    "fs::remove_file / remove_dir / remove_dir_all",
                    "fs::rename(old, new) — 重命名/移动",
                    "fs::copy(src, dst) — 复制文件",
                    "fs::read_dir(path) — 列出目录",
                    "fs::canonicalize(path) — 规范化路径",
                    "fs::set_permissions — 设置权限",
                    "io::stdin() / stdout() / stderr() — 标准流",
                    "io::Error / io::Result — IO 错误和结果",
                    "io::copy(reader, writer) — 复制数据",
                    "io::Cursor — 内存缓冲区作为 IO",
                    "Seek trait — 随机访问",
                    "Read::bytes() — 字节迭代器",
                ],
                "example": """use std::fs::{self, File, OpenOptions};
use std::io::{self, Read, Write, BufReader, BufRead, BufWriter, Seek, SeekFrom};
use std::path::Path;

fn main() -> io::Result<()> {
    // ===== 简单读写 =====
    // 写入文件
    fs::write("test.txt", "Hello, World!\\n第二行\\n第三行\\n")?;

    // 读取为字符串
    let content = fs::read_to_string("test.txt")?;
    println!("文件内容:\\n{}", content);

    // 读取为字节
    let bytes = fs::read("test.txt")?;
    println!("字节数: {}", bytes.len());

    // ===== File 操作 =====
    // 创建并写入
    let mut file = File::create("output.txt")?;
    file.write_all(b"Hello from File\\n")?;
    writeln!(file, "格式化行: {}", 42)?;

    // 打开读取
    let mut file = File::open("output.txt")?;
    let mut s = String::new();
    file.read_to_string(&mut s)?;
    println!("读取: {}", s);

    // OpenOptions 自定义模式
    let mut file = OpenOptions::new()
        .read(true)
        .write(true)
        .append(true)
        .create(true)
        .open("log.txt")?;
    writeln!(file, "追加日志行")?;

    // ===== 缓冲 IO =====
    // BufReader 按行读取
    let file = File::open("test.txt")?;
    let reader = BufReader::new(file);
    for (i, line) in reader.lines().enumerate() {
        println!("行{}: {}", i + 1, line?);
    }

    // BufWriter 批量写入（自动刷新）
    let file = File::create("buffered.txt")?;
    let mut writer = BufWriter::new(file);
    for i in 0..100 {
        writeln!(writer, "行 {}", i)?;
    }
    writer.flush()?; // 手动刷新（drop 时也会自动刷新）

    // ===== 随机访问（Seek）=====
    let mut file = File::open("test.txt")?;
    let mut buf = [0u8; 5];
    file.seek(SeekFrom::Start(7))?; // 跳到第7字节
    file.read_exact(&mut buf)?;
    println!("从位置7读取5字节: {:?}", String::from_utf8_lossy(&buf));

    // ===== 目录操作 =====
    // 创建目录
    fs::create_dir("mydir")?;
    fs::create_dir_all("path/to/dir")?; // 递归创建

    // 列出目录
    for entry in fs::read_dir(".")? {
        let entry = entry?;
        let path = entry.path();
        let metadata = fs::metadata(&path)?;
        println!("  {} ({} bytes, is_dir={})",
            path.display(), metadata.len(), metadata.is_dir());
    }

    // 重命名/移动
    fs::rename("test.txt", "renamed.txt")?;

    // 复制文件
    fs::copy("renamed.txt", "copy.txt")?;

    // 删除
    fs::remove_file("renamed.txt")?;
    fs::remove_file("copy.txt")?;
    fs::remove_dir("mydir")?; // 只能删空目录
    fs::remove_dir_all("path")?; // 递归删除

    // ===== 元数据 =====
    let metadata = fs::metadata("output.txt")?;
    println!("大小: {} bytes", metadata.len());
    println!("权限: {:?}", metadata.permissions());
    println!("修改时间: {:?}", metadata.modified()?);
    println!("创建时间: {:?}", metadata.created()?);
    println!("是文件: {}", metadata.is_file());
    println!("是目录: {}", metadata.is_dir());

    // 判断文件是否存在
    if Path::new("nonexistent.txt").exists() {
        println!("文件存在");
    } else {
        println!("文件不存在");
    }

    // ===== 标准输入输出 =====
    // 读取一行
    let mut input = String::new();
    print!("输入内容: ");
    io::stdout().flush()?;
    io::stdin().read_line(&mut input)?;
    println!("你输入了: {}", input.trim());

    // 读取全部输入
    let mut all_input = String::new();
    // io::stdin().read_to_string(&mut all_input)?;

    // 标准错误
    eprintln!("这是错误输出");

    // ===== io::copy 复制 =====
    let mut src = File::open("output.txt")?;
    let mut dst = File::create("copied.txt")?;
    let copied = io::copy(&mut src, &mut dst)?;
    println!("复制了 {} 字节", copied);

    // ===== Cursor 内存 IO =====
    let mut cursor = io::Cursor::new(Vec::new());
    cursor.write_all(b"hello")?;
    cursor.seek(SeekFrom::Start(0))?;
    let mut result = String::new();
    cursor.read_to_string(&mut result)?;
    println!("Cursor 内容: {}", result);

    // 清理
    fs::remove_file("output.txt")?;
    fs::remove_file("log.txt")?;
    fs::remove_file("buffered.txt")?;
    fs::remove_file("copied.txt")?;

    Ok(())
}""",
                "tips": "fs::read_to_string/write 是最简单的读写方式，但会一次性读入内存；Rust 的 IO 错误用 ? 运算符传播，main 函数返回 io::Result<()>；File::open 是只读，File::create 会截断已有文件，需要追加用 OpenOptions；BufReader/BufWriter 提高 IO 性能，小文件可不用；lines() 返回 Result<String> 的迭代器，每行都要 ?；writeln!/write! 宏需要 use std::io::Write；Seek trait 用于随机访问文件，SeekFrom::Start/Current/End；fs::read_dir 返回 DirEntry 的迭代器，每个 entry 可能有错误；Path/PathBuf 是路径类型，Path 是借用，PathBuf 是拥有；文件权限在 Windows 上大部分无效；删除非空目录用 remove_dir_all，remove_dir 只能删空目录；标准输入 read_line 会包含换行符，用 trim() 去除；io::copy 内部有缓冲，高效复制流。",
            },
            {
                "name": "std::thread / std::sync — 并发编程",
                "desc": "Rust 并发编程核心：std::thread 提供线程创建和管理，std::sync 提供互斥锁、读写锁、原子引用计数、屏障、通道等同步原语，Rust 的所有权系统保证线程安全。",
                "functions": [
                    "thread::spawn(f) — 创建线程",
                    "handle.join() — 等待线程结束",
                    "thread::current() — 当前线程",
                    "thread::sleep(duration) — 线程睡眠",
                    "thread::park() / unpark() — 线程挂起/唤醒",
                    "Builder::new().name().spawn() — 自定义线程",
                    "Mutex<T> — 互斥锁",
                    "mutex.lock() — 获取锁（返回 LockResult<MutexGuard>）",
                    "RwLock<T> — 读写锁",
                    "rwlock.read() / write() — 读/写锁",
                    "Arc<T> — 原子引用计数（线程安全的 Rc）",
                    "arc.clone() — 增加引用计数",
                    "Condvar — 条件变量",
                    "condvar.wait(guard) / notify_one / notify_all",
                    "Barrier — 屏障",
                    "Once — 单次执行",
                    "OnceLock / LazyLock — 延迟初始化静态变量",
                    "mpsc::channel() — 多生产者单消费者通道",
                    "mpsc::sync_channel(bound) — 有界通道",
                    "sender.send(x) / receiver.recv()",
                    "receiver.try_recv() / recv_timeout()",
                    "atomic — 原子类型（AtomicUsize等）",
                    "AtomicUsize::load / store / fetch_add / compare_exchange",
                    "Ordering::SeqCst / Acquire / Release / Relaxed",
                    "scope — 线程作用域（可借用局部变量）",
                    "parking_lot — 第三方更高效的锁库",
                ],
                "example": """use std::thread;
use std::sync::{Mutex, RwLock, Arc, Condvar, Barrier, Once};
use std::sync::mpsc;
use std::time::Duration;
use std::sync::atomic::{AtomicUsize, Ordering};

fn main() {
    // ===== 基本线程 =====
    let handle = thread::spawn(|| {
        for i in 1..=5 {
            println!("子线程: {}", i);
            thread::sleep(Duration::from_millis(100));
        }
    });

    for i in 1..=3 {
        println!("主线程: {}", i);
        thread::sleep(Duration::from_millis(150));
    }

    handle.join().unwrap(); // 等待子线程结束
    println!("子线程已结束");

    // move 闭包（转移所有权到线程）
    let data = vec![1, 2, 3];
    let handle2 = thread::spawn(move || {
        println!("数据: {:?}", data); // data 被移动到子线程
    });
    handle2.join().unwrap();
    // println!("{:?}", data); // 编译错误：data 已被移动

    // ===== Mutex 互斥锁 =====
    let counter = Arc::new(Mutex::new(0));
    let mut handles = vec![];

    for _ in 0..10 {
        let counter = Arc::clone(&counter);
        let handle = thread::spawn(move || {
            let mut num = counter.lock().unwrap();
            *num += 1;
        });
        handles.push(handle);
    }

    for h in handles {
        h.join().unwrap();
    }
    println!("Mutex 计数: {}", *counter.lock().unwrap()); // 10

    // ===== RwLock 读写锁 =====
    let rwlock = Arc::new(RwLock::new(vec![1, 2, 3]));

    // 多个读线程可同时持有读锁
    let r1 = Arc::clone(&rwlock);
    let h1 = thread::spawn(move || {
        let data = r1.read().unwrap();
        println!("读线程1: {:?}", *data);
    });

    let r2 = Arc::clone(&rwlock);
    let h2 = thread::spawn(move || {
        let data = r2.read().unwrap();
        println!("读线程2: {:?}", *data);
    });

    h1.join().unwrap();
    h2.join().unwrap();

    // 写线程独占
    let w = Arc::clone(&rwlock);
    let h3 = thread::spawn(move || {
        let mut data = w.write().unwrap();
        data.push(4);
        println!("写线程: {:?}", *data);
    });
    h3.join().unwrap();

    // ===== Arc 原子引用计数 =====
    let shared = Arc::new(vec![1, 2, 3]);
    let s1 = Arc::clone(&shared); // 引用计数+1
    let s2 = Arc::clone(&shared); // 引用计数+1
    println!("引用计数: {}", Arc::strong_count(&shared)); // 3
    // Arc 内的数据是不可变的，需要可变性用 Mutex/RwLock 包装

    // ===== 通道 mpsc =====
    let (tx, rx) = mpsc::channel();

    // 发送者
    let tx1 = tx.clone();
    thread::spawn(move || {
        for i in 1..=5 {
            tx1.send(format!("消息 {}", i)).unwrap();
            thread::sleep(Duration::from_millis(100));
        }
    });

    // 另一个发送者
    let tx2 = tx.clone();
    thread::spawn(move || {
        for i in 1..=3 {
            tx2.send(format!("另一个消息 {}", i)).unwrap();
            thread::sleep(Duration::from_millis(150));
        }
    });

    drop(tx); // 丢弃原始发送者（否则 recv 不会结束）

    // 接收者（阻塞直到所有发送者都 drop）
    for received in rx {
        println!("收到: {}", received);
    }

    // 有界通道
    let (tx, rx) = mpsc::sync_channel(2); // 缓冲区大小2
    thread::spawn(move || {
        for i in 0..5 {
            tx.send(i).unwrap(); // 缓冲区满时阻塞
            println!("发送: {}", i);
        }
    });
    thread::sleep(Duration::from_millis(500));
    for _ in 0..5 {
        println!("接收: {}", rx.recv().unwrap());
    }

    // try_recv 非阻塞
    let (tx, rx) = mpsc::channel();
    tx.send("hello").unwrap();
    match rx.try_recv() {
        Ok(msg) => println!("非阻塞收到: {}", msg),
        Err(mpsc::TryRecvError::Empty) => println!("无消息"),
        Err(mpsc::TryRecvError::Disconnected) => println!("通道已关闭"),
    }

    // ===== Condvar 条件变量 =====
    let pair = Arc::new((Mutex::new(false), Condvar::new()));
    let pair2 = Arc::clone(&pair);

    thread::spawn(move || {
        let (lock, cvar) = &*pair2;
        let mut started = lock.lock().unwrap();
        *started = true;
        cvar.notify_one(); // 通知等待的线程
    });

    let (lock, cvar) = &*pair;
    let mut started = lock.lock().unwrap();
    while !*started {
        started = cvar.wait(started).unwrap(); // 等待通知
    }
    println!("条件变量已通知");

    // ===== Barrier 屏障 =====
    let barrier = Arc::new(Barrier::new(3));
    let mut handles = vec![];
    for i in 0..3 {
        let b = Arc::clone(&barrier);
        handles.push(thread::spawn(move || {
            println!("线程 {} 到达屏障", i);
            b.wait(); // 等待所有线程到达
            println!("线程 {} 继续执行", i);
        }));
    }
    for h in handles { h.join().unwrap(); }

    // ===== Once 单次执行 =====
    static mut VAL: i32 = 0;
    let once = Arc::new(Once::new());
    let mut handles = vec![];
    for _ in 0..5 {
        let once = Arc::clone(&once);
        handles.push(thread::spawn(move || {
            once.call_once(|| {
                unsafe { VAL = 42; }
                println!("只执行一次");
            });
        }));
    }
    for h in handles { h.join().unwrap(); }
    unsafe { println!("VAL = {}", VAL); }

    // ===== 原子操作 =====
    let counter = Arc::new(AtomicUsize::new(0));
    let mut handles = vec![];
    for _ in 0..1000 {
        let c = Arc::clone(&counter);
        handles.push(thread::spawn(move || {
            c.fetch_add(1, Ordering::SeqCst); // 原子自增
        }));
    }
    for h in handles { h.join().unwrap(); }
    println!("原子计数: {}", counter.load(Ordering::SeqCst)); // 1000

    // ===== 线程作用域（可借用局部变量）=====
    let numbers = vec![1, 2, 3, 4, 5];
    thread::scope(|s| {
        for n in &numbers {
            s.spawn(move || {
                println!("作用域线程: {}", n); // 可以借用 numbers
            });
        }
    }); // 所有线程在此自动 join

    println!("并发演示完成");
}""",
                "tips": "Rust 的线程安全由类型系统保证：Send trait 表示可跨线程转移，Sync 表示可跨线程共享引用；thread::spawn 的闭包默认是 'static 生命周期，需要借用局部变量用 thread::scope；Mutex::lock() 返回 MutexGuard，离开作用域自动解锁，不要手动 unlock；Mutex 中毒（PoisonError）是指持有锁的线程 panic 了，需要 into_inner() 恢复；Arc 是线程安全的引用计数，Rc 不是（单线程用）；Arc 内数据默认不可变，需要可变性用 Arc<Mutex<T>> 或 Arc<RwLock<T>>；mpsc 是多生产者单消费者，多消费者用 crossbeam-channel；通道的 recv() 阻塞，try_recv() 非阻塞，所有发送者 drop 后 recv 返回错误；Condvar 必须配合 Mutex 使用，wait 会原子地释放锁并等待；Barrier 让多个线程在同一点会合；Once 用于线程安全的一次性初始化，静态变量用 OnceLock/LazyLock；原子操作的 Ordering：SeqCst 最安全最慢，Relaxed 最快最弱，Acquire/Release 用于锁实现；Rust 没有数据竞争（编译期保证），但有逻辑竞争需要自己处理。",
            },
            {
                "name": "serde — 序列化与反序列化",
                "desc": "serde 是 Rust 生态最流行的序列化框架，支持 JSON、YAML、TOML、BSON 等多种格式，通过 derive 宏自动为结构体生成序列化代码，高效且零成本抽象。",
                "functions": [
                    "#[derive(Serialize, Deserialize)] — 自动派生",
                    "serde_json::to_string(&v) — 序列化为 JSON 字符串",
                    "serde_json::to_string_pretty(&v) — 格式化 JSON",
                    "serde_json::to_writer(w, &v) — 序列化到 Writer",
                    "serde_json::from_str(s) — 从字符串反序列化",
                    "serde_json::from_reader(r) — 从 Reader 反序列化",
                    "serde_json::Value — 动态 JSON 值类型",
                    "serde_json::json! — 构造 JSON 宏",
                    "#[serde(rename = \"name\")] — 重命名字段",
                    "#[serde(rename_all = \"camelCase\")] — 批量重命名",
                    "#[serde(default)] — 缺失字段用默认值",
                    "#[serde(skip_serializing_if = \"path\")] — 条件跳过",
                    "#[serde(skip)] — 跳过字段",
                    "#[serde(flatten)] — 扁平化嵌套字段",
                    "#[serde(tag = \"type\")] — 枚举标签",
                    "Serialize / Deserialize trait — 自定义实现",
                    "serde_json::Result — 序列化结果类型",
                    "serde_yaml / toml / serde_json — 不同格式",
                ],
                "example": """use serde::{Serialize, Deserialize};
use serde_json::{json, Value, Map};

// ===== 基本派生 =====
#[derive(Debug, Serialize, Deserialize)]
struct User {
    id: u32,
    name: String,
    email: String,
    #[serde(default)]
    age: u32,
    #[serde(skip_serializing_if = "Option::is_none")]
    phone: Option<String>,
    #[serde(skip)]
    password: String, // 永远不序列化
}

#[derive(Debug, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")] // 所有字段转为 camelCase
struct Config {
    max_connections: u32,
    timeout_seconds: u32,
    enable_logging: bool,
}

// ===== 枚举序列化 =====
#[derive(Debug, Serialize, Deserialize)]
#[serde(tag = "type", content = "data")]
enum Message {
    Text { content: String },
    Image { url: String, width: u32, height: u32 },
    System { code: u32 },
}

// ===== 自定义序列化 =====
mod date_format {
    use serde::{self, Serializer, Deserializer};
    use chrono::{NaiveDate, TimeZone, Utc};

    pub fn serialize<S>(date: &NaiveDate, serializer: S) -> Result<S::Ok, S::Error>
    where S: Serializer {
        serializer.serialize_str(&date.format("%Y-%m-%d").to_string())
    }

    pub fn deserialize<'de, D>(deserializer: D) -> Result<NaiveDate, D::Error>
    where D: Deserializer<'de> {
        let s = String::deserialize(deserializer)?;
        NaiveDate::parse_from_str(&s, "%Y-%m-%d").map_err(serde::de::Error::custom)
    }
}

fn main() -> Result<(), Box<dyn std::error::Error>> {
    // ===== 序列化 =====
    let user = User {
        id: 1,
        name: "Alice".to_string(),
        email: "alice@example.com".to_string(),
        age: 25,
        phone: Some("123-456".to_string()),
        password: "secret".to_string(),
    };

    // 序列化为 JSON 字符串
    let json_str = serde_json::to_string(&user)?;
    println!("JSON: {}", json_str);
    // {"id":1,"name":"Alice","email":"alice@example.com","age":25,"phone":"123-456"}

    // 格式化输出
    let pretty = serde_json::to_string_pretty(&user)?;
    println!("格式化:\\n{}", pretty);

    // 序列化到 Vec<u8>
    let bytes = serde_json::to_vec(&user)?;

    // 序列化到 Writer（文件等）
    // let file = std::fs::File::create("user.json")?;
    // serde_json::to_writer(file, &user)?;

    // ===== 反序列化 =====
    let json_data = r#"{"id":2,"name":"Bob","email":"bob@example.com","age":30}"#;
    let user2: User = serde_json::from_str(json_data)?;
    println!("反序列化: {:?}", user2);

    // 从 Reader 反序列化
    // let file = std::fs::File::open("user.json")?;
    // let user3: User = serde_json::from_reader(file)?;

    // 缺失字段用 default
    let partial = r#"{"id":3,"name":"Charlie","email":"c@example.com"}"#;
    let user3: User = serde_json::from_str(partial)?;
    println!("age 默认值: {}", user3.age); // 0

    // ===== 动态 JSON (Value) =====
    let data: Value = serde_json::from_str(r#"{"name":"Alice","scores":[95,87,92]}"#)?;
    println!("name: {}", data["name"]);
    println!("第一个分数: {}", data["scores"][0]);
    println!("不存在的字段: {:?}", data["nonexistent"]); // Null

    // 检查类型
    if data["name"].is_string() {
        println!("name 是字符串");
    }
    if data["scores"].is_array() {
        println!("scores 是数组");
    }

    // 转换为具体类型
    let name: String = serde_json::from_value(data["name"].clone())?;
    let scores: Vec<u32> = serde_json::from_value(data["scores"].clone())?;

    // ===== json! 宏构造 =====
    let dynamic = json!({
        "name": "Alice",
        "age": 25,
        "skills": ["Rust", "Python", "Go"],
        "address": {
            "city": "Beijing",
            "country": "China"
        },
        "active": true
    });
    println!("动态 JSON: {}", serde_json::to_string_pretty(&dynamic)?);

    // 构造数组
    let arr = json!([1, 2, 3, 4, 5]);

    // 构造 Map
    let mut map = Map::new();
    map.insert("key".to_string(), json!("value"));

    // ===== 字段重命名 =====
    let config = Config {
        max_connections: 100,
        timeout_seconds: 30,
        enable_logging: true,
    };
    let config_json = serde_json::to_string(&config)?;
    println!("camelCase: {}", config_json);
    // {"maxConnections":100,"timeoutSeconds":30,"enableLogging":true}

    // ===== 枚举序列化 =====
    let msg1 = Message::Text { content: "Hello".to_string() };
    let msg2 = Message::Image { url: "http://...".to_string(), width: 800, height: 600 };
    println!("消息1: {}", serde_json::to_string(&msg1)?);
    println!("消息2: {}", serde_json::to_string(&msg2)?);

    // 反序列化枚举
    let msg_json = r#"{"type":"Text","data":{"content":"Hi"}}"#;
    let msg: Message = serde_json::from_str(msg_json)?;
    println!("反序列化消息: {:?}", msg);

    // ===== flatten 扁平化 =====
    #[derive(Debug, Serialize, Deserialize)]
    struct Inner {
        a: i32,
        b: i32,
    }
    #[derive(Debug, Serialize, Deserialize)]
    struct Outer {
        name: String,
        #[serde(flatten)]
        inner: Inner,
    }
    let outer = Outer { name: "test".to_string(), inner: Inner { a: 1, b: 2 } };
    println!("flatten: {}", serde_json::to_string(&outer)?);
    // {"name":"test","a":1,"b":2}

    // ===== 错误处理 =====
    let invalid_json = "{invalid}";
    match serde_json::from_str::<User>(invalid_json) {
        Ok(u) => println!("成功: {:?}", u),
        Err(e) => println!("解析错误: {}", e),
    }

    // ===== 其他格式（需要对应 crate）=====
    // YAML: serde_yaml::to_string / from_str
    // TOML: toml::to_string / from_str
    // BSON: bson::to_document / from_document
    // MessagePack: rmp_serde::encode / decode

    Ok(())
}""",
                "tips": "serde 本身不包含具体格式，需要搭配 serde_json/serde_yaml/toml 等 crate；派生宏需要在 Cargo.toml 启用 derive feature：serde = { version = \"1.0\", features = [\"derive\"] }；字段必须是可序列化的，自定义类型也要 derive Serialize/Deserialize；#[serde(default)] 用 Default::default()，也可以指定函数 default = \"path\"；skip_serializing_if 常用 Option::is_none、String::is_empty、Vec::is_empty；rename_all 支持 lowercase、UPPERCASE、PascalCase、camelCase、snake_case、SCREAMING_SNAKE_CASE、kebab-case；枚举序列化默认是外部标签，用 tag 改为内部标签，content 指定内容字段；Value 类型可以动态操作 JSON，但性能和类型安全不如具体结构体；json! 宏可以在运行时构造任意 JSON；自定义序列化实现 Serialize/Deserialize trait，或用 with 属性指定模块；大文件用 from_reader/to_writer 流式处理，避免一次性读入内存；serde 是零成本抽象，派生代码性能接近手写。",
            },
            {
                "name": "std::result / std::option / ? — 错误处理",
                "desc": "Rust 没有异常，用 Result<T,E> 表示可失败操作，Option<T> 表示可空值，? 运算符传播错误，match/if let/while let 处理各种情况，是 Rust 错误处理的核心模式。",
                "functions": [
                    "Result<T, E> — 结果枚举（Ok(T) / Err(E)）",
                    "Option<T> — 可选值枚举（Some(T) / None）",
                    "? — 错误传播运算符（解包或提前返回 Err）",
                    "result.unwrap() — 解包（Err 时 panic）",
                    "result.expect(msg) — 解包（自定义 panic 消息）",
                    "result.unwrap_or(default) — 解包或默认值",
                    "result.unwrap_or_else(f) — 解包或计算默认值",
                    "result.is_ok() / is_err() — 判断状态",
                    "result.ok() — Result 转 Option",
                    "result.err() — 取错误（Option<E>）",
                    "result.map(f) — 转换 Ok 值",
                    "result.map_err(f) — 转换 Err 值",
                    "result.and_then(f) — 链式 Result",
                    "result.or_else(f) — 错误时尝试其他",
                    "option.unwrap() / expect / unwrap_or",
                    "option.is_some() / is_none()",
                    "option.map(f) / and_then(f) / filter(f)",
                    "option.or(other) / or_else(f) / get_or_insert",
                    "option.ok_or(err) / ok_or_else(f) — Option 转 Result",
                    "match — 模式匹配",
                    "if let Some(x) = opt — 简化匹配",
                    "while let Some(x) = iter.next() — 循环匹配",
                    "let else — 提前返回（Rust 1.65+）",
                    "anyhow / thiserror — 第三方错误处理库",
                    "std::error::Error — 错误 trait",
                    "From / Into — 错误转换 trait",
                ],
                "example": """use std::fs::File;
use std::io::{self, Read};
use std::num::ParseIntError;

// ===== 基本 Result =====
fn divide(a: f64, b: f64) -> Result<f64, String> {
    if b == 0.0 {
        Err(String::from("除数不能为零"))
    } else {
        Ok(a / b)
    }
}

// ===== Option =====
fn find_max(numbers: &[i32]) -> Option<i32> {
    if numbers.is_empty() {
        None
    } else {
        Some(*numbers.iter().max().unwrap())
    }
}

fn main() {
    // ===== match 处理 Result =====
    match divide(10.0, 2.0) {
        Ok(result) => println!("10/2 = {}", result),
        Err(e) => println!("错误: {}", e),
    }

    match divide(10.0, 0.0) {
        Ok(result) => println!("结果: {}", result),
        Err(e) => println!("错误: {}", e),
    }

    // ===== unwrap / expect =====
    let r1 = divide(10.0, 2.0).unwrap(); // 5.0
    let r2 = divide(10.0, 2.0).expect("除法失败"); // 5.0
    // divide(10.0, 0.0).unwrap(); // panic!

    // ===== unwrap_or / unwrap_or_else =====
    let r3 = divide(10.0, 0.0).unwrap_or(0.0); // 0.0
    let r4 = divide(10.0, 0.0).unwrap_or_else(|e| {
        eprintln!("计算失败: {}", e);
        -1.0
    });

    // ===== is_ok / is_err =====
    let result = divide(10.0, 2.0);
    if result.is_ok() {
        println!("成功: {}", result.unwrap());
    }
    if result.is_err() {
        println!("失败: {}", result.unwrap_err());
    }

    // ===== map / map_err =====
    let doubled: Result<f64, String> = divide(10.0, 2.0)
        .map(|x| x * 2.0) // 成功时乘以2
        .map_err(|e| format!("计算错误: {}", e)); // 错误时加前缀
    println!("map 结果: {:?}", doubled); // Ok(10.0)

    // ===== and_then 链式 =====
    fn parse_and_divide(s: &str) -> Result<f64, String> {
        s.parse::<f64>()
            .map_err(|e| format!("解析错误: {}", e))
            .and_then(|n| divide(n, 2.0))
    }
    println!("链式: {:?}", parse_and_divide("10")); // Ok(5.0)
    println!("链式: {:?}", parse_and_divide("abc")); // Err

    // ===== ? 运算符传播错误 =====
    fn read_file_contents(path: &str) -> Result<String, io::Error> {
        let mut file = File::open(path)?; // 失败则提前返回 Err
        let mut contents = String::new();
        file.read_to_string(&mut contents)?; // 失败则提前返回 Err
        Ok(contents)
    }

    // 等价于：
    fn read_file_contents2(path: &str) -> Result<String, io::Error> {
        let mut file = match File::open(path) {
            Ok(f) => f,
            Err(e) => return Err(e),
        };
        let mut contents = String::new();
        match file.read_to_string(&mut contents) {
            Ok(_) => Ok(contents),
            Err(e) => Err(e),
        }
    }

    // main 中调用
    match read_file_contents("test.txt") {
        Ok(content) => println!("文件内容: {}", content),
        Err(e) => eprintln!("读取失败: {}", e),
    }

    // ===== Option 处理 =====
    let nums = vec![3, 1, 4, 1, 5, 9];
    match find_max(&nums) {
        Some(max) => println!("最大值: {}", max),
        None => println!("空数组"),
    }

    let empty: Vec<i32> = vec![];
    match find_max(&empty) {
        Some(max) => println!("最大值: {}", max),
        None => println!("空数组"),
    }

    // if let 简化
    let opt = Some(42);
    if let Some(x) = opt {
        println!("if let: {}", x);
    }

    // if let + else
    let opt2: Option<i32> = None;
    if let Some(x) = opt2 {
        println!("值: {}", x);
    } else {
        println!("无值");
    }

    // while let
    let mut stack = vec![1, 2, 3];
    while let Some(top) = stack.pop() {
        println!("弹出: {}", top); // 3, 2, 1
    }

    // let else（Rust 1.65+）
    // let Some(x) = opt else {
    //     eprintln!("无值");
    //     return;
    // };
    // println!("let else: {}", x);

    // ===== Option 的方法 =====
    let opt = Some(5);
    println!("map: {:?}", opt.map(|x| x * 2)); // Some(10)
    println!("and_then: {:?}", opt.and_then(|x| if x > 0 { Some(x * 3) } else { None }));
    println!("filter: {:?}", opt.filter(|x| *x > 10)); // None
    println!("unwrap_or: {}", None.unwrap_or(0)); // 0
    println!("or: {:?}", None.or(Some(1))); // Some(1)

    // ===== Option <-> Result 转换 =====
    let opt = Some(42);
    let result: Result<i32, &str> = opt.ok_or("无值"); // Ok(42)
    let none: Option<i32> = None;
    let result2: Result<i32, &str> = none.ok_or("无值"); // Err("无值")

    let r: Result<i32, &str> = Ok(42);
    let o: Option<i32> = r.ok(); // Some(42)
    let e: Result<i32, &str> = Err("错误");
    let o2: Option<i32> = e.ok(); // None

    // ===== 组合 ? 和 Option =====
    fn get_first_char(s: &str) -> Option<char> {
        s.chars().next()
    }

    fn process(s: Option<&str>) -> Option<char> {
        let s = s?; // None 则提前返回 None
        get_first_char(s)
    }
    println!("process: {:?}", process(Some("hello"))); // Some('h')
    println!("process: {:?}", process(None)); // None

    // ===== 自定义错误类型 =====
    #[derive(Debug)]
    enum AppError {
        Io(io::Error),
        Parse(ParseIntError),
        Validation(String),
    }

    impl std::fmt::Display for AppError {
        fn fmt(&self, f: &mut std::fmt::Formatter) -> std::fmt::Result {
            match self {
                AppError::Io(e) => write!(f, "IO错误: {}", e),
                AppError::Parse(e) => write!(f, "解析错误: {}", e),
                AppError::Validation(msg) => write!(f, "验证错误: {}", msg),
            }
        }
    }

    impl std::error::Error for AppError {}

    impl From<io::Error> for AppError {
        fn from(e: io::Error) -> Self { AppError::Io(e) }
    }

    impl From<ParseIntError> for AppError {
        fn from(e: ParseIntError) -> Self { AppError::Parse(e) }
    }

    fn read_and_parse(path: &str) -> Result<i32, AppError> {
        let content = read_file_contents(path)?; // io::Error -> AppError
        let num: i32 = content.trim().parse()?; // ParseIntError -> AppError
        if num < 0 {
            return Err(AppError::Validation("数字不能为负".to_string()));
        }
        Ok(num)
    }

    // ===== anyhow（第三方，快速开发）=====
    // use anyhow::{Result, Context};
    // fn do_work() -> Result<()> {
    //     let content = read_file_contents("test.txt").context("读取文件失败")?;
    //     Ok(())
    // }

    // ===== thiserror（第三方，库开发）=====
    // use thiserror::Error;
    // #[derive(Error, Debug)]
    // enum MyError {
    //     #[error("IO错误: {0}")]
    //     Io(#[from] io::Error),
    //     #[error("无效输入: {0}")]
    //     Invalid(String),
    // }

    println!("错误处理演示完成");
}""",
                "tips": "Rust 没有异常，所有可失败函数返回 Result<T, E>；? 运算符只能用在返回 Result 或 Option 的函数中；? 会自动通过 From trait 转换错误类型；unwrap/expect 会 panic，只在确定不会失败或示例/测试中用；生产代码用 match 或 ? 处理错误；Option 表示可能不存在的值，不要用 null；Option<T> 相当于其他语言的 T? 或 Maybe<T>；if let 只处理一种情况，其他忽略；while let 常用于迭代器和队列；let else 是 Rust 1.65+ 的新语法，适合提前返回；自定义错误类型实现 Display 和 Error trait，用 From 做自动转换；应用程序用 anyhow（灵活），库用 thiserror（规范）；错误处理原则：能处理就处理，不能处理就传播（?），最上层统一处理；不要用 panic 做错误处理（panic 是不可恢复的）；Result 的 ok() 转 Option 会丢弃错误信息；map_err 可以给错误加上下文信息；and_then 用于链式返回 Result 的函数。",
            },
        ],
    }

_more4 = _more_modules4()
for _k, _v in _more4.items():
    if _k not in LANG_MODULES:
        LANG_MODULES[_k] = _v
del _more4, _more_modules4


def _more_modules5():
    return {
        "csharp": [
            {
                "name": "System.Collections.Generic — 泛型集合",
                "desc": "C# 泛型集合命名空间，提供 List<T>、Dictionary<TKey,TValue>、HashSet<T>、Queue<T>、Stack<T>、SortedDictionary 等强类型集合，是 C# 开发最核心的数据结构库。",
                "functions": [
                    "List<T> — 动态数组（最常用）",
                    "list.Add(item) / AddRange / Insert / Remove / RemoveAt",
                    "list.Count / Capacity / [index]",
                    "list.Find / FindAll / FindIndex / Exists / Contains",
                    "list.Sort / Reverse / Clear / ForEach",
                    "list.Select / Where / OrderBy（LINQ）",
                    "Dictionary<TKey,TValue> — 键值对集合",
                    "dict[key] = value / Add / TryGetValue / Remove",
                    "dict.ContainsKey / ContainsValue / Count",
                    "dict.Keys / Values / KeyValuePair",
                    "HashSet<T> — 不重复集合",
                    "set.Add / Remove / Contains / UnionWith / IntersectWith",
                    "Queue<T> — 队列（FIFO）",
                    "queue.Enqueue / Dequeue / Peek / Count",
                    "Stack<T> — 栈（LIFO）",
                    "stack.Push / Pop / Peek / Count",
                    "SortedDictionary / SortedList / SortedSet — 有序集合",
                    "LinkedList<T> — 双向链表",
                    "ICollection<T> / IEnumerable<T> — 集合接口",
                    "IEnumerator<T> — 枚举器",
                    "yield return — 迭代器语法",
                    "Array — 固定长度数组",
                    "Array.Sort / IndexOf / Copy / Resize",
                ],
                "example": """using System;
using System.Collections.Generic;
using System.Linq;

class Program
{
    static void Main()
    {
        // ===== List<T> =====
        List<int> numbers = new List<int> { 1, 2, 3, 4, 5 };
        numbers.Add(6);
        numbers.AddRange(new[] { 7, 8 });
        numbers.Insert(0, 0); // 在开头插入
        numbers.Remove(3);     // 删除第一个3
        numbers.RemoveAt(0);   // 删除索引0

        Console.WriteLine($"Count: {numbers.Count}");
        Console.WriteLine($"第一个: {numbers[0]}");

        // 遍历
        foreach (int n in numbers) Console.Write(n + " ");
        Console.WriteLine();

        // 查找
        int found = numbers.Find(x => x > 3);
        List<int> evens = numbers.FindAll(x => x % 2 == 0);
        bool hasFive = numbers.Contains(5);
        int index = numbers.IndexOf(5);

        // 排序
        numbers.Sort(); // 升序
        numbers.Sort((a, b) => b.CompareTo(a)); // 降序
        numbers.Reverse();

        // LINQ 操作
        var result = numbers
            .Where(x => x > 2)
            .Select(x => x * 10)
            .OrderByDescending(x => x)
            .ToList();

        // 聚合
        int sum = numbers.Sum();
        int max = numbers.Max();
        int min = numbers.Min();
        double avg = numbers.Average();

        // ===== Dictionary =====
        Dictionary<string, int> scores = new Dictionary<string, int>();
        scores["Alice"] = 95; // 插入或更新
        scores.Add("Bob", 87);
        scores["Charlie"] = 92;

        // 安全访问
        if (scores.TryGetValue("Alice", out int aliceScore))
            Console.WriteLine($"Alice: {aliceScore}");

        if (scores.ContainsKey("Eve"))
            Console.WriteLine("Eve 存在");

        // 遍历
        foreach (KeyValuePair<string, int> kv in scores)
            Console.WriteLine($"{kv.Key}: {kv.Value}");

        foreach (string key in scores.Keys)
            Console.WriteLine(key);

        foreach (int value in scores.Values)
            Console.WriteLine(value);

        // 删除
        scores.Remove("Bob");

        // 统计词频
        string text = "apple banana apple orange banana apple";
        Dictionary<string, int> freq = new Dictionary<string, int>();
        foreach (string word in text.Split())
        {
            freq[word] = freq.TryGetValue(word, out int c) ? c + 1 : 1;
        }

        // ===== HashSet =====
        HashSet<int> set = new HashSet<int> { 1, 2, 3 };
        set.Add(1); // 重复，返回 false
        set.Add(4);
        Console.WriteLine($"包含2: {set.Contains(2)}");
        set.Remove(3);

        // 集合运算
        HashSet<int> a = new HashSet<int> { 1, 2, 3 };
        HashSet<int> b = new HashSet<int> { 2, 3, 4 };
        a.UnionWith(b);        // 并集 {1,2,3,4}
        a.IntersectWith(b);    // 交集 {2,3,4}∩{2,3,4}
        a.ExceptWith(b);       // 差集

        // 去重
        List<int> withDup = new List<int> { 1, 2, 2, 3, 3, 3 };
        HashSet<int> unique = new HashSet<int>(withDup);
        Console.WriteLine($"去重后: {unique.Count} 个");

        // ===== Queue =====
        Queue<string> queue = new Queue<string>();
        queue.Enqueue("第一个");
        queue.Enqueue("第二个");
        queue.Enqueue("第三个");
        Console.WriteLine($"队首: {queue.Peek()}"); // 第一个
        while (queue.Count > 0)
            Console.WriteLine($"出队: {queue.Dequeue()}");

        // ===== Stack =====
        Stack<string> stack = new Stack<string>();
        stack.Push("第一层");
        stack.Push("第二层");
        stack.Push("第三层");
        Console.WriteLine($"栈顶: {stack.Peek()}"); // 第三层
        while (stack.Count > 0)
            Console.WriteLine($"出栈: {stack.Pop()}");

        // ===== SortedDictionary（有序）=====
        SortedDictionary<int, string> sorted = new SortedDictionary<int, string>();
        sorted[3] = "three";
        sorted[1] = "one";
        sorted[2] = "two";
        foreach (var kv in sorted) // 按 key 升序
            Console.WriteLine($"{kv.Key}: {kv.Value}");

        // ===== LinkedList =====
        LinkedList<int> linked = new LinkedList<int>();
        linked.AddLast(1);
        linked.AddLast(2);
        linked.AddFirst(0);
        LinkedListNode<int> node = linked.Find(1);
        linked.AddAfter(node, 5);

        // ===== 数组 =====
        int[] arr = { 5, 2, 8, 1, 9 };
        Array.Sort(arr);
        Array.Reverse(arr);
        int idx = Array.IndexOf(arr, 8);
        int[] copy = new int[5];
        Array.Copy(arr, copy, 5);

        // ===== yield 迭代器 =====
        foreach (int n in GenerateNumbers(5))
            Console.Write(n + " ");
        Console.WriteLine();
    }

    static IEnumerable<int> GenerateNumbers(int count)
    {
        for (int i = 0; i < count; i++)
            yield return i * i; // 延迟生成
    }
}""",
                "tips": "List<T> 是默认选择，底层是数组，随机访问 O(1)，中间插入 O(n)；Dictionary 用哈希表实现，平均 O(1) 查找，不保证顺序；需要有序用 SortedDictionary（O(log n)）；HashSet 本质是 Dictionary<T, byte> 的简化版；Queue/Stack 底层用循环数组实现；泛型集合在编译时检查类型，避免装箱拆箱，比 ArrayList 性能好；集合初始化器 new List<int> {1,2,3} 是语法糖；LINQ 方法不修改原集合，返回新集合（惰性求值）；Dictionary 的 [key] 访问不存在的 key 会抛 KeyNotFoundException，用 TryGetValue 安全访问；foreach 遍历中不能修改集合（添加/删除），否则抛 InvalidOperationException；需要边遍历边删除用 for 循环倒序，或用 RemoveAll；ICollection<T> 继承 IEnumerable<T>，IList<T> 继承 ICollection<T>；yield return 实现状态机，延迟生成序列。",
            },
            {
                "name": "System.IO — 文件与流操作",
                "desc": "C# IO 命名空间提供文件读写、目录操作、流处理（FileStream/MemoryStream/StreamReader/StreamWriter）、路径处理等功能，是 C# 文件和 IO 操作的基础。",
                "functions": [
                    "File.ReadAllText / WriteAllText — 读写整个文本文件",
                    "File.ReadAllLines / WriteAllLines — 按行读写",
                    "File.ReadAllBytes / WriteAllBytes — 读写二进制",
                    "File.AppendAllText / AppendText — 追加内容",
                    "File.Exists / Delete / Copy / Move — 文件操作",
                    "File.Create / Open / OpenRead / OpenText — 打开文件",
                    "File.GetAttributes / SetAttributes — 文件属性",
                    "Directory.Exists / CreateDirectory / Delete",
                    "Directory.GetFiles / GetDirectories / GetFileSystemEntries",
                    "Directory.EnumerateFiles — 延迟枚举文件",
                    "Directory.Move / GetParent / GetCurrentDirectory",
                    "Path.Combine / GetFileName / GetDirectoryName",
                    "Path.GetExtension / GetFileNameWithoutExtension",
                    "Path.GetFullPath / GetTempPath / GetRandomFileName",
                    "FileStream — 文件流（字节级）",
                    "StreamReader / StreamWriter — 文本流",
                    "BinaryReader / BinaryWriter — 二进制流",
                    "MemoryStream — 内存流",
                    "BufferedStream — 缓冲流",
                    "using 语句 — 自动释放资源",
                    "Encoding.UTF8 / Default / ASCII — 编码",
                    "FileInfo / DirectoryInfo — 强类型文件/目录信息",
                    "DriveInfo — 驱动器信息",
                    "FileSystemWatcher — 文件系统监视",
                ],
                "example": """using System;
using System.IO;
using System.Text;
using System.Linq;

class Program
{
    static void Main()
    {
        // ===== 简单文件读写 =====
        // 写入文本
        File.WriteAllText("test.txt", "Hello, World!\\n第二行\\n第三行\\n", Encoding.UTF8);

        // 读取文本
        string content = File.ReadAllText("test.txt", Encoding.UTF8);
        Console.WriteLine(content);

        // 按行读写
        string[] lines = { "第一行", "第二行", "第三行" };
        File.WriteAllLines("lines.txt", lines, Encoding.UTF8);
        string[] readLines = File.ReadAllLines("lines.txt", Encoding.UTF8);
        foreach (string line in readLines)
            Console.WriteLine(line);

        // 追加内容
        File.AppendAllText("test.txt", "追加的一行\\n");

        // 二进制读写
        byte[] data = { 0x48, 0x65, 0x6C, 0x6C, 0x6F }; // "Hello"
        File.WriteAllBytes("binary.dat", data);
        byte[] readData = File.ReadAllBytes("binary.dat");
        Console.WriteLine($"读取 {readData.Length} 字节");

        // ===== 文件操作 =====
        Console.WriteLine($"文件存在: {File.Exists("test.txt")}");
        File.Copy("test.txt", "copy.txt", overwrite: true);
        File.Move("copy.txt", "moved.txt");
        File.Delete("moved.txt");

        // 文件属性
        FileInfo fi = new FileInfo("test.txt");
        Console.WriteLine($"大小: {fi.Length} bytes");
        Console.WriteLine($"创建时间: {fi.CreationTime}");
        Console.WriteLine($"最后修改: {fi.LastWriteTime}");
        Console.WriteLine($"扩展名: {fi.Extension}");
        Console.WriteLine($"完整路径: {fi.FullName}");

        // ===== 目录操作 =====
        Directory.CreateDirectory("mydir");
        Directory.CreateDirectory("path/to/dir"); // 递归创建

        Console.WriteLine($"目录存在: {Directory.Exists("mydir")}");

        // 列出文件
        string[] files = Directory.GetFiles(".", "*.txt");
        foreach (string f in files)
            Console.WriteLine($"  文件: {Path.GetFileName(f)}");

        // 列出目录
        string[] dirs = Directory.GetDirectories(".");
        foreach (string d in dirs)
            Console.WriteLine($"  目录: {Path.GetFileName(d)}");

        // 延迟枚举（大目录用这个，不一次性加载）
        var txtFiles = Directory.EnumerateFiles(".", "*.txt", SearchOption.AllDirectories);
        foreach (string f in txtFiles.Take(10))
            Console.WriteLine($"  找到: {f}");

        Directory.Move("mydir", "renamed_dir");
        Directory.Delete("renamed_dir"); // 只能删空目录
        Directory.Delete("path", recursive: true); // 递归删除

        // ===== 路径处理 =====
        string path = Path.Combine("dir", "subdir", "file.txt");
        Console.WriteLine($"拼接: {path}");
        Console.WriteLine($"文件名: {Path.GetFileName(path)}"); // file.txt
        Console.WriteLine($"目录: {Path.GetDirectoryName(path)}");
        Console.WriteLine($"扩展名: {Path.GetExtension(path)}"); // .txt
        Console.WriteLine($"无扩展名: {Path.GetFileNameWithoutExtension(path)}");
        Console.WriteLine($"绝对路径: {Path.GetFullPath(path)}");
        Console.WriteLine($"临时目录: {Path.GetTempPath()}");
        Console.WriteLine($"随机文件名: {Path.GetRandomFileName()}");
        Console.WriteLine($"临时文件: {Path.GetTempFileName()}");

        // ===== 流操作（using 自动释放）=====
        // FileStream 字节级读写
        using (FileStream fs = File.Create("stream.dat"))
        {
            byte[] buffer = Encoding.UTF8.GetBytes("Hello from FileStream");
            fs.Write(buffer, 0, buffer.Length);
        }

        using (FileStream fs = File.OpenRead("stream.dat"))
        {
            byte[] buffer = new byte[1024];
            int bytesRead = fs.Read(buffer, 0, buffer.Length);
            string text = Encoding.UTF8.GetString(buffer, 0, bytesRead);
            Console.WriteLine($"读取: {text}");
        }

        // StreamReader/StreamWriter 文本读写
        using (StreamWriter writer = new StreamWriter("output.txt", false, Encoding.UTF8))
        {
            writer.WriteLine("第一行");
            writer.WriteLine("第二行");
            writer.Write("不换行的");
            writer.WriteLine("内容");
        }

        using (StreamReader reader = new StreamReader("output.txt", Encoding.UTF8))
        {
            string line;
            while ((line = reader.ReadLine()) != null)
                Console.WriteLine($"行: {line}");
        }

        // 读取到末尾
        using (StreamReader reader = new StreamReader("output.txt"))
        {
            string all = reader.ReadToEnd();
            Console.WriteLine(all);
        }

        // BinaryWriter/BinaryReader 二进制
        using (BinaryWriter bw = new BinaryWriter(File.Create("binary2.dat")))
        {
            bw.Write(42);
            bw.Write(3.14);
            bw.Write("hello");
            bw.Write(true);
        }

        using (BinaryReader br = new BinaryReader(File.OpenRead("binary2.dat")))
        {
            int i = br.ReadInt32();
            double d = br.ReadDouble();
            string s = br.ReadString();
            bool b = br.ReadBoolean();
            Console.WriteLine($"二进制: {i}, {d}, {s}, {b}");
        }

        // MemoryStream 内存流
        using (MemoryStream ms = new MemoryStream())
        {
            byte[] bytes = Encoding.UTF8.GetBytes("in memory");
            ms.Write(bytes, 0, bytes.Length);
            ms.Position = 0; // 重置位置
            using (StreamReader sr = new StreamReader(ms))
            {
                Console.WriteLine($"内存流: {sr.ReadToEnd()}");
            }
        }

        // ===== 驱动器信息 =====
        foreach (DriveInfo drive in DriveInfo.GetDrives())
        {
            if (drive.IsReady)
            {
                Console.WriteLine($"{drive.Name} 总大小: {drive.TotalSize / 1024 / 1024 / 1024}GB, " +
                    $"可用: {drive.AvailableFreeSpace / 1024 / 1024 / 1024}GB");
            }
        }

        // 清理
        File.Delete("test.txt");
        File.Delete("lines.txt");
        File.Delete("binary.dat");
        File.Delete("stream.dat");
        File.Delete("output.txt");
        File.Delete("binary2.dat");
    }
}""",
                "tips": "File.ReadAllText/WriteAllText 是最简单的方式，但会一次性读入内存，大文件用流式；始终用 using 语句释放流资源（IDisposable）；编码显式指定 Encoding.UTF8，不要依赖默认编码；路径拼接用 Path.Combine，不要手动拼字符串（跨平台分隔符）；Directory.Delete 默认只删空目录，递归删除用 recursive: true；GetFiles 一次性返回所有文件，大目录用 EnumerateFiles 延迟枚举；FileInfo/DirectoryInfo 是实例类，缓存属性，适合多次操作同一文件；FileSystemWatcher 监视文件变化，但有事件丢失和缓冲区溢出问题；StreamReader 的 ReadLine 返回 null 表示到达末尾；BinaryWriter 写字符串会先写长度前缀；MemoryStream 用于在内存中操作字节，可转换为 byte[]；异步 IO 用 ReadAsync/WriteAsync（await）；临时文件用 Path.GetTempFileName()，用完删除。",
            },
            {
                "name": "System.Linq — LINQ 查询",
                "desc": "LINQ（Language Integrated Query）是 C# 语言集成查询，提供统一的语法查询各种数据源（集合、XML、数据库、JSON），支持过滤、映射、排序、分组、连接、聚合等操作，是 C# 最强大的特性之一。",
                "functions": [
                    "Where(predicate) — 过滤",
                    "Select(selector) — 映射",
                    "SelectMany — 扁平化映射",
                    "OrderBy / OrderByDescending — 排序",
                    "ThenBy / ThenByDescending — 次级排序",
                    "GroupBy(keySelector) — 分组",
                    "Join / GroupJoin — 连接",
                    "Count / LongCount — 计数",
                    "Sum / Min / Max / Average — 聚合",
                    "Aggregate — 自定义归约",
                    "First / FirstOrDefault — 第一个",
                    "Last / LastOrDefault — 最后一个",
                    "Single / SingleOrDefault — 唯一元素",
                    "ElementAt / ElementAtOrDefault — 指定位置",
                    "Any / All / Contains — 判断",
                    "Take / TakeLast / TakeWhile — 取前N个",
                    "Skip / SkipLast / SkipWhile — 跳过",
                    "Distinct — 去重",
                    "Concat / Union / Intersect / Except — 集合运算",
                    "Zip — 合并两个序列",
                    "Reverse — 反转",
                    "ToList / ToArray / ToDictionary / ToHashSet — 收集",
                    "AsEnumerable / AsQueryable — 转换",
                    "from...where...select... 查询语法",
                    "let — 查询语法中的中间变量",
                    "into — 查询语法中的延续",
                    "IEnumerable<T> / IQueryable<T> — 查询接口",
                    "IEqualityComparer<T> — 自定义比较器",
                ],
                "example": """using System;
using System.Collections.Generic;
using System.Linq;

class Program
{
    class Student
    {
        public string Name { get; set; }
        public int Age { get; set; }
        public string City { get; set; }
        public int Score { get; set; }
        public List<string> Skills { get; set; }
    }

    static void Main()
    {
        List<Student> students = new List<Student>
        {
            new Student { Name = "Alice", Age = 20, City = "北京", Score = 95, Skills = new List<string>{"C#", "Java"} },
            new Student { Name = "Bob", Age = 22, City = "上海", Score = 87, Skills = new List<string>{"Python", "Go"} },
            new Student { Name = "Charlie", Age = 21, City = "北京", Score = 92, Skills = new List<string>{"C#", "Rust"} },
            new Student { Name = "Diana", Age = 23, City = "广州", Score = 88, Skills = new List<string>{"Java", "Python"} },
            new Student { Name = "Eve", Age = 20, City = "上海", Score = 91, Skills = new List<string>{"C#", "Go"} },
        };

        // ===== Where 过滤 =====
        var beijingStudents = students.Where(s => s.City == "北京").ToList();
        var highScorers = students.Where(s => s.Score >= 90 && s.Age < 22);

        // ===== Select 映射 =====
        var names = students.Select(s => s.Name).ToList();
        var nameAndScore = students.Select(s => new { s.Name, s.Score }); // 匿名类型
        var withGrade = students.Select(s => new
        {
            s.Name,
            Grade = s.Score >= 90 ? "A" : s.Score >= 80 ? "B" : "C"
        });

        // ===== SelectMany 扁平化 =====
        var allSkills = students.SelectMany(s => s.Skills).Distinct().ToList();
        Console.WriteLine("所有技能: " + string.Join(", ", allSkills));

        // 带索引的 SelectMany
        var skillWithStudent = students
            .SelectMany(s => s.Skills, (student, skill) => $"{student.Name}: {skill}");

        // ===== 排序 =====
        var sortedByScore = students.OrderByDescending(s => s.Score).ToList();
        var sortedByCityThenAge = students
            .OrderBy(s => s.City)
            .ThenByDescending(s => s.Age)
            .ToList();

        // ===== 分组 =====
        var byCity = students.GroupBy(s => s.City);
        foreach (var group in byCity)
        {
            Console.WriteLine($"城市: {group.Key}, 人数: {group.Count()}");
            foreach (var s in group)
                Console.WriteLine($"  {s.Name} ({s.Score})");
        }

        // 分组 + 聚合
        var cityStats = students
            .GroupBy(s => s.City)
            .Select(g => new
            {
                City = g.Key,
                Count = g.Count(),
                AvgScore = g.Average(s => s.Score),
                MaxScore = g.Max(s => s.Score),
                Students = g.Select(s => s.Name).ToList()
            })
            .ToList();

        foreach (var stat in cityStats)
            Console.WriteLine($"{stat.City}: {stat.Count}人, 平均{stat.AvgScore:F1}, 最高{stat.MaxScore}");

        // ===== 聚合 =====
        int totalScore = students.Sum(s => s.Score);
        double avgAge = students.Average(s => s.Age);
        int maxScore = students.Max(s => s.Score);
        int minScore = students.Min(s => s.Score);
        int count = students.Count(s => s.Score >= 90);

        // Aggregate 自定义归约
        string allNames = students.Aggregate("", (acc, s) => acc + s.Name + ", ");
        int product = students.Aggregate(1, (acc, s) => acc * s.Score);

        // ===== 查找元素 =====
        Student first = students.First(s => s.City == "北京"); // 不存在则抛异常
        Student firstOrDefault = students.FirstOrDefault(s => s.City == "深圳"); // null
        Student single = students.Single(s => s.Name == "Alice"); // 多个则抛异常
        Student singleOrDefault = students.SingleOrDefault(s => s.Name == "Nobody");
        Student last = students.Last(s => s.Score > 90);
        Student elementAt = students.ElementAt(2);

        // ===== 判断 =====
        bool anyBeijing = students.Any(s => s.City == "北京");
        bool allAdult = students.All(s => s.Age >= 18);
        bool containsAlice = students.Any(s => s.Name == "Alice");

        // ===== 分页 =====
        var page1 = students.OrderBy(s => s.Name).Skip(0).Take(2).ToList();
        var page2 = students.OrderBy(s => s.Name).Skip(2).Take(2).ToList();

        // ===== 集合运算 =====
        List<int> a = new List<int> { 1, 2, 3, 4 };
        List<int> b = new List<int> { 3, 4, 5, 6 };
        var union = a.Union(b).ToList();        // {1,2,3,4,5,6}
        var intersect = a.Intersect(b).ToList(); // {3,4}
        var except = a.Except(b).ToList();       // {1,2}
        var concat = a.Concat(b).ToList();       // {1,2,3,4,3,4,5,6}

        // ===== Zip 合并 =====
        var zipped = a.Zip(b, (x, y) => x + y).ToList(); // {4,6,8,10}

        // ===== 查询语法（SQL 风格）=====
        var querySyntax = from s in students
                          where s.Score >= 90
                          orderby s.Score descending
                          select new { s.Name, s.Score, s.City };

        // 查询语法 + let + group
        var queryWithLet = from s in students
                            let grade = s.Score >= 90 ? "优秀" : "良好"
                            group s by grade into g
                            select new { Grade = g.Key, Count = g.Count() };

        // 连接两个集合
        var cities = new List<(string Name, string Province)>
        {
            ("北京", "北京"), ("上海", "上海"), ("广州", "广东")
        };
        var joined = students.Join(cities,
            s => s.City,
            c => c.Name,
            (s, c) => new { s.Name, s.City, c.Province });

        // ===== ToDictionary / ToLookup =====
        Dictionary<string, Student> byName = students.ToDictionary(s => s.Name);
        ILookup<string, Student> lookupByCity = students.ToLookup(s => s.City);
        var beijingGroup = lookupByCity["北京"]; // 不存在返回空序列

        // ===== 惰性求值 =====
        var lazyQuery = students.Where(s =>
        {
            Console.WriteLine($"过滤 {s.Name}"); // 不会立即执行
            return s.Score > 90;
        });
        Console.WriteLine("--- 开始枚举 ---");
        foreach (var s in lazyQuery) // 此时才执行过滤
            Console.WriteLine(s.Name);

        // ===== 自定义比较器 =====
        var distinctByCity = students
            .GroupBy(s => s.City)
            .Select(g => g.First())
            .ToList();

        Console.WriteLine("LINQ 演示完成");
    }
}""",
                "tips": "LINQ 方法语法（Method Syntax）和查询语法（Query Syntax）等价，编译器互相转换；LINQ 是惰性求值（deferred execution），直到枚举（foreach/ToList/Count）才执行；Where/Select 等返回 IEnumerable<T>，不修改原集合；聚合方法（Count/Sum/Max 等）立即执行；First/Single/Any/All 立即执行；First 找不到抛异常，FirstOrDefault 返回默认值（null/0）；Single 要求恰好一个，0个或多个都抛异常；OrderBy 返回 IOrderedEnumerable<T>，后续排序用 ThenBy；GroupBy 返回 IGrouping<TKey, TElement>，Key 属性获取分组键；SelectMany 用于一对多关系扁平化；Join 是内连接，GroupJoin 是左外连接；ToDictionary 的 key 必须唯一，否则抛异常；ToLookup 允许重复 key，返回 ILookup；IQueryable<T> 用于远程数据源（EF Core），表达式树翻译为 SQL；IEnumerable<T> 用于内存集合；复杂查询用查询语法更清晰，简单链式用方法语法；避免在 LINQ 中写副作用（Console.WriteLine 等），因为惰性求值可能多次执行。",
            },
            {
                "name": "System.Threading / Tasks — 异步与并发",
                "desc": "C# 异步编程核心：async/await 语法糖、Task/Task<T> 异步任务、Thread 线程、ThreadPool 线程池、Parallel 并行循环、CancellationToken 取消、SemaphoreSlim 信号量等，是 C# 高并发编程的基础。",
                "functions": [
                    "async / await — 异步语法",
                    "Task — 异步任务（无返回值）",
                    "Task<T> — 异步任务（有返回值）",
                    "Task.Run(action) — 在线程池运行任务",
                    "Task.Delay(ms) — 异步延迟",
                    "Task.WhenAll(tasks) — 等待所有任务",
                    "Task.WhenAny(tasks) — 等待任一任务",
                    "Task.FromResult(value) — 已完成的任务",
                    "Task.CompletedTask — 已完成的空任务",
                    "task.Wait() / Result — 阻塞等待（避免使用）",
                    "task.GetAwaiter().GetResult() — 阻塞并抛出原始异常",
                    "CancellationTokenSource — 取消令牌源",
                    "CancellationToken — 取消令牌",
                    "cts.Cancel() / CancelAfter(ms)",
                    "token.ThrowIfCancellationRequested()",
                    "IProgress<T> / Progress<T> — 进度报告",
                    "Thread — 线程类",
                    "ThreadPool.QueueUserWorkItem — 线程池",
                    "Parallel.For / ForEach — 并行循环",
                    "Parallel.Invoke — 并行调用",
                    "lock(obj) — 锁语句",
                    "Monitor.Enter / Exit / Wait / Pulse",
                    "Mutex / Semaphore / SemaphoreSlim",
                    "ReaderWriterLockSlim — 读写锁",
                    "ManualResetEventSlim / AutoResetEvent",
                    "ConcurrentDictionary / ConcurrentQueue — 并发集合",
                    "Interlocked — 原子操作",
                    "Channel<T> — 通道（生产者消费者）",
                    "ValueTask / ValueTask<T> — 轻量任务",
                    "ConfigureAwait(false) — 不恢复上下文",
                ],
                "example": """using System;
using System.Collections.Generic;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;
using System.Collections.Concurrent;
using System.Diagnostics;

class Program
{
    // ===== async/await 基本用法 =====
    static async Task<string> DownloadDataAsync(string url)
    {
        await Task.Delay(1000); // 模拟异步操作
        return $"数据来自 {url}";
    }

    static async Task<int> CalculateSumAsync(int n)
    {
        await Task.Delay(500);
        return Enumerable.Range(1, n).Sum();
    }

    static async Task Main()
    {
        // ===== 基本异步 =====
        Console.WriteLine("开始异步操作...");
        string result = await DownloadDataAsync("https://example.com");
        Console.WriteLine(result);

        // ===== Task.Run（CPU 密集型）=====
        int sum = await Task.Run(() =>
        {
            int s = 0;
            for (int i = 0; i < 1000000; i++) s += i;
            return s;
        });
        Console.WriteLine($"Task.Run 结果: {sum}");

        // ===== 并行执行（WhenAll）=====
        Stopwatch sw = Stopwatch.StartNew();
        Task<string> t1 = DownloadDataAsync("url1");
        Task<string> t2 = DownloadDataAsync("url2");
        Task<string> t3 = DownloadDataAsync("url3");

        // 串行需要 3 秒，并行只需 1 秒
        string[] results = await Task.WhenAll(t1, t2, t3);
        Console.WriteLine($"WhenAll 耗时: {sw.ElapsedMilliseconds}ms");
        foreach (string r in results) Console.WriteLine(r);

        // WhenAny（任一完成）
        Task<string> firstDone = await Task.WhenAny(t1, t2, t3);
        Console.WriteLine($"第一个完成: {firstDone.Result}");

        // ===== 异常处理 =====
        try
        {
            await MightFailAsync();
        }
        catch (Exception ex)
        {
            Console.WriteLine($"捕获异常: {ex.Message}");
        }

        // WhenAll 的异常（AggregateException）
        var tasks = new[] { MightFailAsync(), DownloadDataAsync("ok") };
        try
        {
            await Task.WhenAll(tasks);
        }
        catch (Exception)
        {
            // 只捕获第一个异常
            // 所有异常在 Task.Exception.InnerExceptions
            var allExceptions = tasks.Where(t => t.IsFaulted)
                .SelectMany(t => t.Exception.InnerExceptions);
            foreach (var ex in allExceptions)
                Console.WriteLine($"异常: {ex.Message}");
        }

        // ===== CancellationToken 取消 =====
        var cts = new CancellationTokenSource();
        cts.CancelAfter(2000); // 2秒后自动取消

        try
        {
            await LongRunningAsync(cts.Token);
        }
        catch (OperationCanceledException)
        {
            Console.WriteLine("操作已取消");
        }

        // 手动取消
        var cts2 = new CancellationTokenSource();
        Task task = LongRunningAsync(cts2.Token);
        await Task.Delay(500);
        cts2.Cancel(); // 取消
        try { await task; } catch (OperationCanceledException) { }

        // ===== 进度报告 =====
        var progress = new Progress<int>(percent =>
        {
            Console.WriteLine($"进度: {percent}%");
        });
        await ProcessWithProgressAsync(progress);

        // ===== Thread =====
        Thread thread = new Thread(() =>
        {
            for (int i = 0; i < 5; i++)
            {
                Console.WriteLine($"子线程: {i}");
                Thread.Sleep(100);
            }
        });
        thread.Start();
        thread.Join(); // 等待线程结束

        // ===== ThreadPool =====
        for (int i = 0; i < 10; i++)
        {
            ThreadPool.QueueUserWorkItem(state =>
            {
                int id = (int)state;
                Console.WriteLine($"线程池任务 {id}, 线程ID: {Thread.CurrentThread.ManagedThreadId}");
            }, i);
        }
        Thread.Sleep(1000); // 等待完成

        // ===== Parallel 并行循环 =====
        var numbers = Enumerable.Range(1, 100).ToList();
        var results2 = new ConcurrentBag<int>();
        Parallel.ForEach(numbers, n =>
        {
            results2.Add(n * n);
        });
        Console.WriteLine($"Parallel 结果数: {results2.Count}");

        Parallel.For(0, 10, i =>
        {
            Console.WriteLine($"并行 For: {i}, 线程: {Thread.CurrentThread.ManagedThreadId}");
        });

        // ===== lock 同步 =====
        var counter = new Counter();
        var tasks3 = Enumerable.Range(0, 1000)
            .Select(_ => Task.Run(() => counter.Increment()))
            .ToArray();
        await Task.WhenAll(tasks3);
        Console.WriteLine($"lock 计数: {counter.Value}"); // 1000

        // ===== 并发集合 =====
        var concurrentDict = new ConcurrentDictionary<string, int>();
        concurrentDict["key"] = 1;
        concurrentDict.AddOrUpdate("key", 1, (k, v) => v + 1);
        int value;
        if (concurrentDict.TryGetValue("key", out value))
            Console.WriteLine($"ConcurrentDictionary: {value}");

        var queue = new ConcurrentQueue<int>();
        queue.Enqueue(1);
        queue.Enqueue(2);
        if (queue.TryDequeue(out int dequeued))
            Console.WriteLine($"ConcurrentQueue: {dequeued}");

        // ===== SemaphoreSlim 限流 =====
        var semaphore = new SemaphoreSlim(3); // 最多3个并发
        var limitedTasks = Enumerable.Range(0, 10)
            .Select(async i =>
            {
                await semaphore.WaitAsync();
                try
                {
                    Console.WriteLine($"任务 {i} 开始 (并发限制)");
                    await Task.Delay(100);
                }
                finally { semaphore.Release(); }
            })
            .ToArray();
        await Task.WhenAll(limitedTasks);

        // ===== Interlocked 原子操作 =====
        int atomicCounter = 0;
        var atomicTasks = Enumerable.Range(0, 1000)
            .Select(_ => Task.Run(() => Interlocked.Increment(ref atomicCounter)))
            .ToArray();
        await Task.WhenAll(atomicTasks);
        Console.WriteLine($"Interlocked 计数: {atomicCounter}"); // 1000

        // ===== ConfigureAwait =====
        // 库代码中用 ConfigureAwait(false) 避免死锁
        await DownloadDataAsync("url").ConfigureAwait(false);

        Console.WriteLine("异步并发演示完成");
    }

    static async Task MightFailAsync()
    {
        await Task.Delay(100);
        throw new InvalidOperationException("模拟错误");
    }

    static async Task LongRunningAsync(CancellationToken token)
    {
        for (int i = 0; i < 100; i++)
        {
            token.ThrowIfCancellationRequested();
            await Task.Delay(100, token);
            Console.WriteLine($"长时间运行: {i}%");
        }
    }

    static async Task ProcessWithProgressAsync(IProgress<int> progress)
    {
        for (int i = 0; i <= 100; i += 20)
        {
            await Task.Delay(200);
            progress.Report(i);
        }
    }

    class Counter
    {
        private readonly object _lock = new object();
        public int Value { get; private set; }
        public void Increment()
        {
            lock (_lock) { Value++; }
        }
    }
}""",
                "tips": "async 方法返回 Task/Task<T>/void（避免 void，除了事件处理器）；await 不会阻塞线程，会释放线程继续执行其他工作；async 方法名以 Async 结尾（约定）；避免用 .Result 或 .Wait() 阻塞，可能导致死锁，用 await；Task.Run 用于 CPU 密集型操作，IO 密集型直接用 async API；WhenAll 并行执行独立任务，比逐个 await 快；WhenAll 中任一任务失败会抛 AggregateException，await 时只抛出第一个，需要检查所有任务的 Exception；CancellationToken 传递到所有可取消的异步操作；用 CancellationTokenSource.CancelAfter 设置超时；IProgress<T> 用于报告进度，Progress<T> 的回调在 UI 线程执行；lock 是 Monitor 的语法糖，锁对象用 private readonly object；避免 lock(this) 或 lock(string)（外部可能也锁）；Concurrent 集合是线程安全的，优先于 lock+普通集合；Interlocked 用于简单原子操作（计数），复杂状态用 lock；SemaphoreSlim 用于限流，WaitAsync 是异步的；ConfigureAwait(false) 在库代码中使用，避免捕获同步上下文；async Main 是 C# 7.1+ 支持；ValueTask 用于可能同步完成的异步操作，减少分配；Parallel 适合 CPU 密集型、无依赖、可并行的循环，IO 密集型用 Task.WhenAll；线程池线程是后台线程，进程退出时不等待。",
            },
            {
                "name": "System.Text.Json — JSON 序列化",
                "desc": "System.Text.Json 是 .NET Core 3.0+ 内置的高性能 JSON 序列化库，支持序列化/反序列化、JsonDocument  DOM 解析、Utf8JsonWriter/Reader 低级别 API、源生成器等，是现代 .NET JSON 处理的首选。",
                "functions": [
                    "JsonSerializer.Serialize(obj) — 序列化为 JSON 字符串",
                    "JsonSerializer.Serialize(obj, options) — 带选项序列化",
                    "JsonSerializer.Deserialize<T>(json) — 反序列化",
                    "JsonSerializer.Deserialize(json, type) — 非泛型反序列化",
                    "JsonSerializerOptions — 序列化选项",
                    "options.WriteIndented — 格式化输出",
                    "options.PropertyNamingPolicy — 属性命名策略（CamelCase）",
                    "options.IgnoreNullValues — 忽略 null",
                    "options.DefaultIgnoreCondition — 忽略条件",
                    "options.Converters.Add — 自定义转换器",
                    "options.MaxDepth — 最大深度",
                    "[JsonPropertyName(\"name\")] — 指定 JSON 属性名",
                    "[JsonIgnore] — 忽略属性",
                    "[JsonIgnore(Condition = ...)] — 条件忽略",
                    "[JsonPropertyOrder] — 属性顺序",
                    "[JsonExtensionData] — 扩展数据字典",
                    "[JsonConstructor] — 指定反序列化构造函数",
                    "JsonDocument.Parse(json) — 解析为 DOM",
                    "JsonElement — DOM 元素",
                    "element.GetProperty / TryGetProperty",
                    "element.GetString / GetInt32 / GetBoolean / GetArray",
                    "element.EnumerateObject / EnumerateArray",
                    "Utf8JsonWriter — 低级别写入器",
                    "Utf8JsonReader — 低级别读取器",
                    "JsonNode — 可变 JSON DOM（.NET 6+）",
                    "JsonObject / JsonArray / JsonValue",
                    "JsonSerializer.SerializeToUtf8Bytes — 序列化为字节",
                    "JsonSerializer.DeserializeAsync — 异步反序列化",
                    "JsonSourceGeneration — 源生成器（AOT 优化）",
                ],
                "example": """using System;
using System.Collections.Generic;
using System.IO;
using System.Text;
using System.Text.Json;
using System.Text.Json.Serialization;

class Program
{
    // ===== 基本模型 =====
    public class User
    {
        [JsonPropertyName("id")]
        public int Id { get; set; }

        [JsonPropertyName("name")]
        public string Name { get; set; }

        [JsonPropertyName("email")]
        public string Email { get; set; }

        [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
        public string Phone { get; set; }

        [JsonIgnore]
        public string Password { get; set; } // 永远不序列化

        [JsonPropertyName("age")]
        public int Age { get; set; }

        [JsonPropertyName("tags")]
        public List<string> Tags { get; set; }

        [JsonPropertyName("createdAt")]
        public DateTime CreatedAt { get; set; }
    }

    public class Config
    {
        public int MaxConnections { get; set; }
        public int TimeoutSeconds { get; set; }
        public bool EnableLogging { get; set; }
        public Dictionary<string, string> Settings { get; set; }
    }

    static void Main()
    {
        // ===== 基本序列化 =====
        var user = new User
        {
            Id = 1,
            Name = "Alice",
            Email = "alice@example.com",
            Age = 25,
            Phone = "123-456",
            Password = "secret",
            Tags = new List<string> { "admin", "editor" },
            CreatedAt = DateTime.Now
        };

        // 默认序列化
        string json = JsonSerializer.Serialize(user);
        Console.WriteLine("默认: " + json);

        // 格式化输出
        string pretty = JsonSerializer.Serialize(user, new JsonSerializerOptions
        {
            WriteIndented = true
        });
        Console.WriteLine("格式化:\\n" + pretty);

        // CamelCase 命名策略
        var camelCaseOptions = new JsonSerializerOptions
        {
            PropertyNamingPolicy = JsonNamingPolicy.CamelCase,
            WriteIndented = true
        };
        string camelJson = JsonSerializer.Serialize(user, camelCaseOptions);
        Console.WriteLine("CamelCase:\\n" + camelJson);

        // ===== 反序列化 =====
        string jsonData = @"{""id"":2,""name"":""Bob"",""email"":""bob@example.com"",""age"":30,""tags"":[""user""],""createdAt"":""2024-01-01T00:00:00""}";

        User user2 = JsonSerializer.Deserialize<User>(jsonData);
        Console.WriteLine($"反序列化: {user2.Name}, {user2.Age}岁");

        // 反序列化为字典（动态）
        Dictionary<string, object> dict = JsonSerializer
            .Deserialize<Dictionary<string, object>>(jsonData);
        Console.WriteLine("字典 name: " + dict["name"]);

        // 反序列化为 JsonElement
        using JsonDocument doc = JsonDocument.Parse(jsonData);
        JsonElement root = doc.RootElement;
        Console.WriteLine("JsonElement name: " + root.GetProperty("name").GetString());
        Console.WriteLine("JsonElement age: " + root.GetProperty("age").GetInt32());

        // 遍历属性
        foreach (JsonProperty prop in root.EnumerateObject())
        {
            Console.WriteLine($"  {prop.Name}: {prop.Value.ValueKind}");
        }

        // 数组遍历
        if (root.TryGetProperty("tags", out JsonElement tags))
        {
            foreach (JsonElement tag in tags.EnumerateArray())
                Console.WriteLine("  tag: " + tag.GetString());
        }

        // ===== JsonNode（可变 DOM，.NET 6+）=====
        JsonNode node = JsonNode.Parse(jsonData);
        Console.WriteLine("JsonNode: " + node["name"].GetValue<string>());
        node["age"] = 31; // 修改
        node["newField"] = "value"; // 添加
        Console.WriteLine("修改后: " + node.ToJsonString());

        // 构造 JsonObject
        var obj = new JsonObject
        {
            ["name"] = "Charlie",
            ["age"] = 28,
            ["skills"] = new JsonArray { "C#", "Python", "Go" }
        };
        Console.WriteLine("构造: " + obj.ToJsonString());

        // ===== 序列化选项 =====
        var options = new JsonSerializerOptions
        {
            WriteIndented = true,
            PropertyNamingPolicy = JsonNamingPolicy.CamelCase,
            DefaultIgnoreCondition = JsonIgnoreCondition.WhenWritingNull,
            MaxDepth = 64,
            AllowTrailingCommas = true,
            ReadCommentHandling = JsonCommentHandling.Skip
        };

        // 忽略 null 值
        var userWithNull = new User { Id = 3, Name = "Diana", Email = "d@example.com" };
        string noNullJson = JsonSerializer.Serialize(userWithNull, options);
        Console.WriteLine("忽略null:\\n" + noNullJson);

        // ===== 集合序列化 =====
        var users = new List<User>
        {
            new User { Id = 1, Name = "Alice", Email = "a@example.com" },
            new User { Id = 2, Name = "Bob", Email = "b@example.com" }
        };
        string listJson = JsonSerializer.Serialize(users, options);
        Console.WriteLine("列表: " + listJson);

        List<User> deserializedList = JsonSerializer.Deserialize<List<User>>(listJson);
        Console.WriteLine($"反序列化列表: {deserializedList.Count} 个");

        // 字典序列化
        var config = new Config
        {
            MaxConnections = 100,
            TimeoutSeconds = 30,
            EnableLogging = true,
            Settings = new Dictionary<string, string>
            {
                ["theme"] = "dark",
                ["language"] = "zh-CN"
            }
        };
        string configJson = JsonSerializer.Serialize(config, options);
        Console.WriteLine("配置: " + configJson);

        // ===== 异步序列化 =====
        // using (var stream = new MemoryStream())
        // {
        //     await JsonSerializer.SerializeAsync(stream, user, options);
        //     stream.Position = 0;
        //     User deserialized = await JsonSerializer.DeserializeAsync<User>(stream);
        // }

        // ===== Utf8JsonWriter 低级别 =====
        using (var ms = new MemoryStream())
        {
            using (var writer = new Utf8JsonWriter(ms, new JsonWriterOptions { Indented = true }))
            {
                writer.WriteStartObject();
                writer.WriteString("name", "Eve");
                writer.WriteNumber("age", 22);
                writer.WriteBoolean("active", true);
                writer.WriteStartArray("skills");
                writer.WriteStringValue("C#");
                writer.WriteStringValue("Rust");
                writer.WriteEndArray();
                writer.WriteEndObject();
            }
            string lowLevelJson = Encoding.UTF8.GetString(ms.ToArray());
            Console.WriteLine("低级别: " + lowLevelJson);
        }

        // ===== 自定义转换器 =====
        // public class DateTimeConverter : JsonConverter<DateTime>
        // {
        //     public override DateTime Read(ref Utf8JsonReader reader, Type type, JsonSerializerOptions options)
        //         => DateTime.ParseExact(reader.GetString(), "yyyy-MM-dd", CultureInfo.InvariantCulture);
        //     public override void Write(Utf8JsonWriter writer, DateTime value, JsonSerializerOptions options)
        //         => writer.WriteStringValue(value.ToString("yyyy-MM-dd"));
        // }
        // options.Converters.Add(new DateTimeConverter());

        // ===== JsonExtensionData（捕获未知字段）=====
        public class FlexibleModel
        {
            public string KnownField { get; set; }

            [JsonExtensionData]
            public Dictionary<string, JsonElement> ExtraFields { get; set; }
        }

        string flexibleJson = @"{""KnownField"":""value"",""Unknown1"":1,""Unknown2"":""test""}";
        FlexibleModel flexible = JsonSerializer.Deserialize<FlexibleModel>(flexibleJson);
        Console.WriteLine($"已知字段: {flexible.KnownField}");
        foreach (var kv in flexible.ExtraFields)
            Console.WriteLine($"  扩展字段: {kv.Key} = {kv.Value}");

        // ===== 性能提示 =====
        // - System.Text.Json 比 Newtonsoft.Json 快 2-3 倍，内存占用少
        // - 源生成器（.NET 6+）可进一步提升启动性能和减少内存
        // - 大文件用 Utf8JsonWriter/Reader 流式处理
        // - 默认不支持注释和尾逗号，需显式启用

        Console.WriteLine("JSON 序列化演示完成");
    }
}""",
                "tips": "System.Text.Json 是 .NET Core 3.0+ 内置，无需额外 NuGet 包；默认属性名区分大小写，反序列化时用 PropertyNameCaseInsensitive = true 忽略大小写；默认不支持 JSON 中的注释（//）和尾逗号，需 AllowTrailingCommas/ReadCommentHandling；DateTime 默认序列化为 ISO 8601 格式；JsonDocument 是只读的，需要修改用 JsonNode（.NET 6+）；JsonDocument 实现 IDisposable，用 using 释放（利用 pooled memory）；JsonPropertyName 指定序列化名称，不影响 C# 属性名；[JsonIgnore] 永远忽略，[JsonIgnore(Condition)] 条件忽略；JsonExtensionData 捕获未知字段到字典，向前兼容；自定义转换器继承 JsonConverter<T>，实现 Read/Write；源生成器（JsonSourceGeneration）用于 AOT 和启动优化，.NET 6+；序列化到 Stream 用 SerializeAsync/DeserializeAsync；大 JSON 用 Utf8JsonReader/Writer 流式处理，不加载整个 DOM；默认最大深度 64，可配置 MaxDepth；从 Newtonsoft.Json 迁移注意：没有 JObject/JArray，用 JsonNode/JsonObject；没有 [JsonProperty]，用 [JsonPropertyName]；没有 Formatting.Indented，用 WriteIndented。",
            },
        ],
    }

_more5 = _more_modules5()
for _k, _v in _more5.items():
    if _k not in LANG_MODULES:
        LANG_MODULES[_k] = _v
del _more5, _more_modules5


def _more_modules6():
    return {
        "swift": [
            {
                "name": "Array / Dictionary / Set — 集合类型",
                "desc": "Swift 标准库集合类型：Array 有序数组、Dictionary 键值对字典、Set 无序不重复集合，均为值类型（写时复制），支持泛型、字面量初始化、丰富的高阶函数。",
                "functions": [
                    "Array<Element> / [Element] — 数组类型",
                    "[1, 2, 3] — 数组字面量",
                    "Array(repeating:count:) — 重复元素初始化",
                    "arr.append(x) / append(contentsOf:) — 追加",
                    "arr.insert(x,at:) / remove(at:) / removeAll()",
                    "arr.count / isEmpty / capacity",
                    "arr[i] / arr[startIndex] / arr[endIndex]",
                    "arr.first / last / firstIndex(of:)",
                    "arr.contains(x) / contains(where:)",
                    "arr.filter { } / map { } / flatMap / compactMap",
                    "arr.reduce(initial) { } / sorted(by:)",
                    "arr.forEach { } / enumerated()",
                    "arr.prefix(n) / suffix(n) / dropFirst(n)",
                    "arr.joined(separator:) — 字符串数组连接",
                    "arr.min() / max() / sum()",
                    "Dictionary<Key,Value> / [Key:Value] — 字典",
                    "dict[key] = value / updateValue(forKey:)",
                    "dict[key] / dict[key, default:]",
                    "dict.removeValue(forKey:) / removeAll()",
                    "dict.keys / values / count / isEmpty",
                    "dict.contains(where:) / mapValues",
                    "dict.merge(other, uniquingKeysWith:)",
                    "Set<Element> — 集合（无序不重复）",
                    "set.insert(x) / remove(x) / contains(x)",
                    "set.union / intersection / symmetricDifference / subtracting",
                    "set.isSubset(of:) / isSuperset(of:)",
                    "set.isEmpty / count / sorted()",
                    "for-in 遍历 / for (index, value) in arr.enumerated()",
                    "if let first = arr.first — 可选绑定",
                    "arr.randomElement() — 随机元素",
                    "arr.swapAt(i,j) — 交换",
                    "arr.withUnsafeBufferPointer — 底层指针访问",
                ],
                "example": """import Foundation

// ===== Array 数组 =====
var numbers: [Int] = [1, 2, 3, 4, 5]
var emptyArray: [String] = []
var zeros = Array(repeating: 0, count: 5) // [0,0,0,0,0]

// 增删改
numbers.append(6)
numbers.append(contentsOf: [7, 8])
numbers.insert(0, at: 0)
numbers.remove(at: 0)
numbers.removeLast()
// numbers.removeAll()

// 访问
print("第一个: \\(numbers.first ?? 0)") // 可选类型
print("最后一个: \\(numbers.last ?? 0)")
print("索引2: \\(numbers[2])")
print("count: \\(numbers.count)")
print("isEmpty: \\(numbers.isEmpty)")

// 遍历
for n in numbers {
    print(n, terminator: " ")
}
print()

for (index, value) in numbers.enumerated() {
    print("[\(index)] = \\(value)")
}

// ===== 高阶函数 =====
let doubled = numbers.map { $0 * 2 }
let evens = numbers.filter { $0 % 2 == 0 }
let sum = numbers.reduce(0, +)
let sortedDesc = numbers.sorted(by: >)
let hasFive = numbers.contains(5)
let firstEven = numbers.first { $0 % 2 == 0 }

// flatMap / compactMap
let nested = [[1, 2], [3, 4], [5, 6]]
let flattened = nested.flatMap { $0 } // [1,2,3,4,5,6]

let strings = ["1", "2", "three", "4"]
let ints = strings.compactMap { Int($0) } // [1,2,4]（过滤nil）

// 切片
let firstThree = numbers.prefix(3)
let lastTwo = numbers.suffix(2)
let withoutFirst = numbers.dropFirst()

// 字符串数组连接
let words = ["Hello", "World", "Swift"]
let sentence = words.joined(separator: " ")
print(sentence) // "Hello World Swift"

// 聚合
let total = numbers.reduce(0) { $0 + $1 }
let product = numbers.reduce(1, *)

// ===== Dictionary 字典 =====
var scores: [String: Int] = ["Alice": 95, "Bob": 87]
var emptyDict: [String: Int] = [:]

// 增删改查
scores["Charlie"] = 92 // 插入或更新
scores["Alice"] = 98   // 更新
scores.updateValue(88, forKey: "Diana")

// 访问（返回可选类型）
if let aliceScore = scores["Alice"] {
    print("Alice: \\(aliceScore)")
}

// 默认值（避免可选）
let eveScore = scores["Eve", default: 0]
print("Eve: \\(eveScore)") // 0

// 删除
scores["Bob"] = nil
scores.removeValue(forKey: "Charlie")
// scores.removeAll()

// 遍历
for (name, score) in scores {
    print("\\(name): \\(score)")
}

for name in scores.keys {
    print(name)
}

for score in scores.values {
    print(score)
}

// 字典高阶函数
let highScores = scores.filter { $0.value >= 90 }
let scoreStrings = scores.mapValues { "\\($0)分" }

// 合并字典
let moreScores = ["Eve": 85, "Frank": 78]
scores.merge(moreScores) { current, _ in current } // 冲突保留原值

// 从数组构建字典
let people = [("Alice", 25), ("Bob", 30), ("Charlie", 28)]
let ageDict = Dictionary(uniqueKeysWithValues: people)

// 分组
let grouped = Dictionary(grouping: words) { $0.first! }
// ["H": ["Hello"], "W": ["World"], "S": ["Swift"]]

// ===== Set 集合 =====
var setA: Set<Int> = [1, 2, 3, 4, 5]
var setB: Set<Int> = [4, 5, 6, 7, 8]

// 增删查
setA.insert(6)
setA.remove(1)
print("包含3: \\(setA.contains(3))")
print("count: \\(setA.count)")

// 集合运算
let union = setA.union(setB)           // 并集
let intersection = setA.intersection(setB) // 交集
let symmetric = setA.symmetricDifference(setB) // 对称差
let subtracting = setA.subtracting(setB) // 差集

// 子集判断
let smallSet: Set<Int> = [2, 3]
print("是子集: \\(smallSet.isSubset(of: setA))")
print("是超集: \\(setA.isSuperset(of: smallSet))")

// 遍历（有序遍历用 sorted）
for item in setA.sorted() {
    print(item, terminator: " ")
}
print()

// 去重
let withDuplicates = [1, 2, 2, 3, 3, 3, 4]
let unique = Array(Set(withDuplicates)) // 顺序不定
let uniqueOrdered = withDuplicates.reduce(into: []) { result, item in
    if !result.contains(item) { result.append(item) }
}

// ===== 可选类型与集合 =====
let optionalArray: [Int]? = [1, 2, 3]
if let arr = optionalArray {
    print("数组有 \\(arr.count) 个元素")
}

// if let 解包集合元素
let firstItem = numbers.first
if let item = firstItem {
    print("第一个元素: \\(item)")
}

// guard let（提前退出）
func processFirst(_ arr: [Int]) {
    guard let first = arr.first else {
        print("空数组")
        return
    }
    print("第一个: \\(first)")
}

// ===== 范围与切片 =====
let range = 0..<5 // 半开区间
let closedRange = 0...5 // 闭区间
let partial = ...5 // 部分区间

let subArray = numbers[1...3] // ArraySlice
let converted = Array(subArray) // 转回 Array

// ===== 写时复制（Copy-on-Write）=====
var original = [1, 2, 3]
var copy = original // 不复制，共享底层
copy.append(4)      // 此时才复制
print("original: \\(original)") // [1,2,3]
print("copy: \\(copy)")         // [1,2,3,4]

print("集合类型演示完成")""",
                "tips": "Swift 集合是值类型，赋值时复制（写时复制优化，修改时才真正复制）；数组索引越界会 crash（不是返回 nil），用 first/last 安全访问；字典下标返回可选类型，用 if let 或 default 子句；Set 元素必须符合 Hashable 协议；数组排序用 sorted(by:)，原数组排序用 sort(by:)；map 不修改原数组返回新数组，compactMap 过滤 nil；reduce 的第一个参数是初始值；for-in 遍历字典时顺序不确定，需要有序用 sorted；ArraySlice 是数组的视图，不是新数组，长期持有会引用整个原数组内存，转成 Array 再保存；字典的 keys/values 是延迟视图，需要 Array() 转数组；contains(where:) 用于自定义条件判断；Set 不保证顺序，遍历时用 sorted() 获得有序结果；Swift 5.7+ 支持 if let shorthand（if let first { } 代替 if let first = first）；多集合操作（union/intersection）不修改原集合，返回新集合；用 reserveCapacity(_:) 预分配容量避免多次扩容。",
            },
            {
                "name": "String — 字符串处理",
                "desc": "Swift String 是 Unicode 正确的字符集合，值类型，支持字符串插值、下标、子串、常用操作（拼接、查找、替换、分割、大小写转换等），与 NSString 无缝桥接。",
                "functions": [
                    "\"\\(expr)\" — 字符串插值",
                    "str.count — 字符数（不是字节数）",
                    "str.isEmpty / isEmpty",
                    "str.append(c) / str += other",
                    "str.hasPrefix(prefix) / hasSuffix(suffix)",
                    "str.contains(other) / contains(where:)",
                    "str.lowercased() / uppercased() / capitalized",
                    "str.trimmingCharacters(in:)",
                    "str.prefix(n) / suffix(n) / dropFirst(n)",
                    "str.first / last / firstIndex(of:)",
                    "str.index(after:) / index(before:) / index(_:offsetBy:)",
                    "str.startIndex / endIndex",
                    "str[range] — 下标取子串（返回 Substring）",
                    "str.split(separator:) / split(maxSplits:omittingEmptySubsequences:)",
                    "str.components(separatedBy:) — 按字符串分割",
                    "str.replacingOccurrences(of:with:)",
                    "str.replacingCharacters(in:with:)",
                    "str.remove(at:) / removeSubrange(_:)",
                    "str.insert(c,at:) / insert(contentsOf:at:)",
                    "str.enumerated() — 带索引遍历",
                    "str.map { } / filter / reduce",
                    "str.utf8 / utf16 / unicodeScalars — 编码视图",
                    "String(repeating:count:) — 重复字符串",
                    "String(format:arguments:) — 格式化字符串",
                    "str.localizedLowercase / localizedUppercase",
                    "str.compare(_:options:) — 比较",
                    "str.commonPrefix(with:options:)",
                    "str.advanced(by:) — 索引偏移",
                    "Substring — 子串类型（高效，共享存储）",
                    "String(substring) — Substring 转 String",
                    "Character — 字符类型",
                    "str.unicodeScalars — Unicode 标量",
                ],
                "example": """import Foundation

// ===== 基本操作 =====
var greeting = "Hello"
greeting += ", World!"
print(greeting) // "Hello, World!"

let name = "Swift"
let version = 5.9
let message = "欢迎使用 \\(name) \\(version)" // 字符串插值
print(message)

// 多行字符串
let multiLine = \"\"\"
这是第一行
这是第二行
    这是缩进的第三行
\"\"\"
print(multiLine)

// 原始字符串（#...#，不解析转义）
let raw = #"这包含 \n 但不换行，\(name) 也不插值"#
print(raw)
let rawInterpolated = #"插值需要 \#(name)"#
print(rawInterpolated)

// ===== 长度与访问 =====
let str = "Hello, 世界! 🌍"
print("字符数: \\(str.count)") // 12（Unicode 字符，不是字节）
print("isEmpty: \\(str.isEmpty)")
print("第一个字符: \\(str.first ?? "无")") // H
print("最后一个字符: \\(str.last ?? "无")") // 🌍

// 遍历字符
for char in str {
    print(char, terminator: " ")
}
print()

// 带索引遍历
for (index, char) in str.enumerated() {
    print("[\(index)] = \\(char)")
}

// ===== 前缀后缀与包含 =====
let fileName = "document.pdf"
print("有前缀 doc: \\(fileName.hasPrefix("doc"))")
print("有后缀 .pdf: \\(fileName.hasSuffix(".pdf"))")
print("包含 'ment': \\(fileName.contains("ment"))")

let email = "user@example.com"
print("包含 @: \\(email.contains("@"))")
print("包含数字: \\(email.contains { $0.isNumber })")

// ===== 大小写转换 =====
let text = "Hello, World!"
print("小写: \\(text.lowercased())")       // hello, world!
print("大写: \\(text.uppercased())")       // HELLO, WORLD!
print("首字母大写: \\(text.capitalized)")   // Hello, World!

// ===== 修剪 =====
let padded = "   你好，世界！   "
let trimmed = padded.trimmingCharacters(in: .whitespacesAndNewlines)
print("修剪后: [\\(trimmed)]")

let numeric = "123abc456"
let lettersOnly = numeric.trimmingCharacters(in: .decimalDigits)
print("去掉数字: \\(lettersOnly)") // abc

// ===== 索引与下标 =====
let hello = "Hello, World!"
let start = hello.startIndex
let end = hello.endIndex

// index 操作
let commaIndex = hello.firstIndex(of: ",")!
let afterComma = hello.index(after: commaIndex)
let fifthIndex = hello.index(start, offsetBy: 5)

// 下标取子串（返回 Substring）
let firstWord = hello[start..<commaIndex] // "Hello"
let rest = hello[afterComma..<end]        // " World!"
let prefix5 = hello.prefix(5)              // "Hello"
let suffix6 = hello.suffix(6)              // "World!"
let withoutFirst = hello.dropFirst(7)      // "World!"

// Substring 转 String（长期存储时）
let storedString = String(firstWord)

// ===== 分割与连接 =====
let csv = "apple,banana,orange,grape"
let fruits = csv.split(separator: ",") // [Substring]
print("分割: \\(fruits)")

// 按字符串分割（Foundation）
let sentence2 = "Hello World Swift"
let words2 = sentence2.components(separatedBy: " ")
print("按空格分割: \\(words2)")

// 多行分割
let lines = "line1\\nline2\\nline3".split(separator: "\\n")

// 连接
let joined = fruits.joined(separator: " | ")
print("连接: \\(joined)") // apple | banana | orange | grape

let withComma = ["a", "b", "c"].joined(separator: ", ")

// ===== 替换 =====
var mutable = "Hello, World!"
mutable.replaceSubrange(mutable.startIndex..<mutable.index(mutable.startIndex, offsetBy: 5), with: "Hi")
print("替换后: \\(mutable)") // Hi, World!

// replacingOccurrences（不修改原字符串）
let original2 = "Hello, Hello, World!"
let replaced = original2.replacingOccurrences(of: "Hello", with: "Hi")
print("全部替换: \\(replaced)") // Hi, Hi, World!

// 只替换前两个
var count = 0
let limitedReplace = original2.replacingOccurrences(of: "Hello", with: "Hi") { _ in
    count += 1
    return count <= 2
}

// ===== 查找 =====
let searchText = "The quick brown fox jumps over the lazy dog"
if let foxRange = searchText.range(of: "fox") {
    print("找到 fox 在: \\(foxRange)")
    let beforeFox = searchText[searchText.startIndex..<foxRange.lowerBound]
    print("fox 之前: \\(beforeFox)")
}

// 查找所有出现位置
var allRanges: [Range<String.Index>] = []
var searchStart = searchText.startIndex
while let range = searchText[searchStart...].range(of: "the") {
    allRanges.append(range)
    searchStart = range.upperBound
}
print("找到 'the' \\(allRanges.count) 次")

// ===== 字符属性 =====
let mixed = "Hello123!@#"
for char in mixed {
    if char.isLetter { print("\\(char) 是字母") }
    if char.isNumber { print("\\(char) 是数字") }
    if char.isPunctuation { print("\\(char) 是标点") }
    if char.isWhitespace { print("\\(char) 是空白") }
    if char.isUppercase { print("\\(char) 是大写") }
}

// ===== 高阶函数 =====
let chars = "Hello".map { $0.lowercased() } // ["h","e","l","l","o"]
let vowels = "Hello World".filter { "aeiou".contains($0.lowercased()) }
let charSum = "12345".reduce(0) { $0 + (Int(String($1)) ?? 0) }

// 反转
let reversed = String("Hello".reversed()) // "olleH"

// ===== 格式化字符串 =====
let pi = 3.14159
let formatted = String(format: "%.2f", pi) // "3.14"
let padded2 = String(format: "%05d", 42)   // "00042"
let hex = String(format: "%X", 255)         // "FF"

// 日期格式化（DateFormatter）
let formatter = DateFormatter()
formatter.dateFormat = "yyyy-MM-dd HH:mm:ss"
let dateStr = formatter.string(from: Date())
print("当前时间: \\(dateStr)")

// ===== Unicode =====
let emoji = "🌍"
print("🌍 的 UTF-8 字节: \\(Array(emoji.utf8))")
print("🌍 的 Unicode 标量: \\(emoji.unicodeScalars.map { $0.value })")

// 组合字符（é 可以是单个字符或 e + 组合重音）
let composed = "café"
let decomposed = "cafe\\u{0301}"
print("相等: \\(composed == decomposed)") // true（Unicode 规范化）
print("composed 字符数: \\(composed.count)") // 4
print("decomposed 字符数: \\(decomposed.count)") // 4（Swift 自动规范化）

// ===== 与 NSString 桥接 =====
let nsString = "Hello" as NSString
let swiftString = nsString as String

// NSString 的方法也可用（通过桥接）
let nsRange = (text as NSString).range(of: "World")
print("NSRange: \\(nsRange)")

print("字符串处理演示完成")""",
                "tips": "Swift String 是 Unicode 正确的，count 是字符数不是字节数（中文和 emoji 各算一个字符）；String 不能直接用整数下标（如 str[5]），必须用 String.Index，因为字符是变长编码；firstIndex(of:) 返回可选索引，不存在返回 nil；Substring 是字符串的视图，共享底层存储，高效但不适合长期存储（会持有整个原字符串），转 String 再保存；字符串是值类型，修改时写时复制；多行字符串用 \"\"\"...\"\"\"，缩进以结束引号为基准；原始字符串 #\"...\"# 不解析转义符，插值用 \\#()；trimmingCharacters(in:) 只修剪两端，中间不处理；split(separator:) 返回 [Substring]，components(separatedBy:) 返回 [String]（需要 Foundation）；replacingOccurrences 不修改原字符串，返回新字符串；DateFormatter 创建开销大，复用实例；NSString 的 range(of:) 返回 NSRange，需要转换为 Range<String.Index> 才能用在 Swift String 上；字符判断用 isLetter/isNumber/isWhitespace 等属性；.utf8/.utf16/.unicodeScalars 提供不同编码视图；String(format:) 来自 Foundation，是 C 风格格式化。",
            },
            {
                "name": "URLSession — 网络请求",
                "desc": "URLSession 是 Swift/iOS 网络请求核心 API，支持 HTTP/HTTPS 请求、数据任务、上传下载任务、后台传输、缓存、Cookie、认证等，现代 Swift 支持 async/await 异步语法。",
                "functions": [
                    "URLSession.shared — 共享会话（基本配置）",
                    "URLSession(configuration:) — 自定义会话",
                    "URLSessionConfiguration.default / ephemeral / background",
                    "URL(string:) — 创建 URL（返回可选）",
                    "URLRequest(url:) — 创建请求",
                    "request.httpMethod — GET/POST/PUT/DELETE",
                    "request.setValue(_:forHTTPHeaderField:) — 设置请求头",
                    "request.httpBody — 请求体（Data）",
                    "request.timeoutInterval — 超时时间",
                    "session.dataTask(with:completionHandler:) — 数据任务",
                    "session.data(for:) — async/await 数据任务",
                    "session.uploadTask(with:from:) — 上传任务",
                    "session.downloadTask(with:) — 下载任务",
                    "task.resume() — 启动任务",
                    "task.cancel() — 取消任务",
                    "task.suspend() — 暂停任务",
                    "HTTPURLResponse — HTTP 响应（statusCode/headers）",
                    "response.statusCode — 状态码",
                    "response.allHeaderFields — 响应头",
                    "response.mimeType — MIME 类型",
                    "JSONEncoder / JSONDecoder — JSON 编解码",
                    "encoder.outputFormatting = .prettyPrinted",
                    "decoder.keyDecodingStrategy = .convertFromSnakeCase",
                    "URLComponents — 构造 URL（查询参数）",
                    "URLQueryItem — 查询参数项",
                    "MultipartFormData — 多部分表单（需自己构造或用库）",
                    "URLCache — 缓存配置",
                    "URLSessionDelegate — 会话代理（认证/重定向等）",
                    "URLSessionDataDelegate — 数据任务代理",
                    "URLSessionDownloadDelegate — 下载任务代理",
                    "result.get() — 获取 Result 成功值或抛异常",
                ],
                "example": """import Foundation

// ===== 数据模型 =====
struct User: Codable {
    let id: Int
    let name: String
    let email: String
}

struct CreateUserRequest: Codable {
    let name: String
    let email: String
}

// ===== 基本 GET 请求（async/await，现代 Swift）=====
func fetchUser(id: Int) async throws -> User {
    guard let url = URL(string: "https://api.example.com/users/\\(id)") else {
        throw URLError(.badURL)
    }

    let (data, response) = try await URLSession.shared.data(from: url)

    // 检查 HTTP 状态码
    guard let httpResponse = response as? HTTPURLResponse,
          (200...299).contains(httpResponse.statusCode) else {
        throw URLError(.badServerResponse)
    }

    let decoder = JSONDecoder()
    return try decoder.decode(User.self, from: data)
}

// ===== 带请求头的 GET =====
func fetchProtectedData(token: String) async throws -> Data {
    guard let url = URL(string: "https://api.example.com/protected") else {
        throw URLError(.badURL)
    }

    var request = URLRequest(url: url)
    request.httpMethod = "GET"
    request.setValue("Bearer \\(token)", forHTTPHeaderField: "Authorization")
    request.setValue("application/json", forHTTPHeaderField: "Accept")
    request.timeoutInterval = 30

    let (data, response) = try await URLSession.shared.data(for: request)

    guard let httpResponse = response as? HTTPURLResponse,
          httpResponse.statusCode == 200 else {
        throw URLError(.badServerResponse)
    }

    return data
}

// ===== POST 请求（JSON 体）=====
func createUser(name: String, email: String) async throws -> User {
    guard let url = URL(string: "https://api.example.com/users") else {
        throw URLError(.badURL)
    }

    let requestBody = CreateUserRequest(name: name, email: email)
    let encoder = JSONEncoder()
    encoder.outputFormatting = .prettyPrinted

    var request = URLRequest(url: url)
    request.httpMethod = "POST"
    request.setValue("application/json", forHTTPHeaderField: "Content-Type")
    request.httpBody = try encoder.encode(requestBody)

    let (data, response) = try await URLSession.shared.data(for: request)

    guard let httpResponse = response as? HTTPURLResponse,
          httpResponse.statusCode == 201 else { // 201 Created
        throw URLError(.badServerResponse)
    }

    return try JSONDecoder().decode(User.self, from: data)
}

// ===== PUT / DELETE 请求 =====
func updateUser(id: Int, name: String) async throws {
    guard let url = URL(string: "https://api.example.com/users/\\(id)") else {
        throw URLError(.badURL)
    }

    var request = URLRequest(url: url)
    request.httpMethod = "PUT"
    request.setValue("application/json", forHTTPHeaderField: "Content-Type")
    request.httpBody = try JSONEncoder().encode(["name": name])

    let (_, response) = try await URLSession.shared.data(for: request)
    guard let httpResponse = response as? HTTPURLResponse,
          (200...299).contains(httpResponse.statusCode) else {
        throw URLError(.badServerResponse)
    }
}

func deleteUser(id: Int) async throws {
    guard let url = URL(string: "https://api.example.com/users/\\(id)") else {
        throw URLError(.badURL)
    }

    var request = URLRequest(url: url)
    request.httpMethod = "DELETE"

    let (_, response) = try await URLSession.shared.data(for: request)
    guard let httpResponse = response as? HTTPURLResponse,
          httpResponse.statusCode == 204 else { // 204 No Content
        throw URLError(.badServerResponse)
    }
}

// ===== URLComponents 构造带查询参数的 URL =====
func searchUsers(query: String, page: Int, limit: Int) async throws -> [User] {
    var components = URLComponents(string: "https://api.example.com/users/search")
    components?.queryItems = [
        URLQueryItem(name: "q", value: query),
        URLQueryItem(name: "page", value: "\\(page)"),
        URLQueryItem(name: "limit", value: "\\(limit)")
    ]

    guard let url = components?.url else {
        throw URLError(.badURL)
    }
    print("请求 URL: \\(url.absoluteString)")

    let (data, _) = try await URLSession.shared.data(from: url)
    return try JSONDecoder().decode([User].self, from: data)
}

// ===== 自定义 URLSession =====
func makeCustomSession() -> URLSession {
    let config = URLSessionConfiguration.default
    config.timeoutIntervalForRequest = 30
    config.timeoutIntervalForResource = 300
    config.httpAdditionalHeaders = ["X-App-Version": "1.0"]
    config.requestCachePolicy = .reloadIgnoringLocalCacheData
    // config.urlCache = URLCache(memoryCapacity: 10_000_000, diskCapacity: 100_000_000)
    return URLSession(configuration: config)
}

// ===== 下载任务 =====
func downloadFile(url: URL, destination: URL) async throws {
    let (tempURL, response) = try await URLSession.shared.download(from: url)

    guard let httpResponse = response as? HTTPURLResponse,
          httpResponse.statusCode == 200 else {
        throw URLError(.badServerResponse)
    }

    // 移动临时文件到目标位置
    if FileManager.default.fileExists(atPath: destination.path) {
        try FileManager.default.removeItem(at: destination)
    }
    try FileManager.default.moveItem(at: tempURL, to: destination)
}

// ===== 上传任务 =====
func uploadFile(data: Data, to url: URL) async throws {
    var request = URLRequest(url: url)
    request.httpMethod = "POST"
    request.setValue("application/octet-stream", forHTTPHeaderField: "Content-Type")

    let (_, response) = try await URLSession.shared.upload(for: request, from: data)
    guard let httpResponse = response as? HTTPURLResponse,
          (200...299).contains(httpResponse.statusCode) else {
        throw URLError(.badServerResponse)
    }
}

// ===== 多部分表单上传（Multipart Form Data）=====
func uploadMultipart(fileData: Data, fileName: String, to url: URL) async throws {
    let boundary = "Boundary-\\(UUID().uuidString)"
    var request = URLRequest(url: url)
    request.httpMethod = "POST"
    request.setValue("multipart/form-data; boundary=\\(boundary)",
                     forHTTPHeaderField: "Content-Type")

    var body = Data()
    body.append("--\\(boundary)\\r\\n".data(using: .utf8)!)
    body.append("Content-Disposition: form-data; name=\\"file\\"; filename=\\"\\(fileName)\\"\\r\\n".data(using: .utf8)!)
    body.append("Content-Type: application/octet-stream\\r\\n\\r\\n".data(using: .utf8)!)
    body.append(fileData)
    body.append("\\r\\n".data(using: .utf8)!)
    body.append("--\\(boundary)--\\r\\n".data(using: .utf8)!)

    request.httpBody = body

    let (_, response) = try await URLSession.shared.data(for: request)
    guard let httpResponse = response as? HTTPURLResponse,
          (200...299).contains(httpResponse.statusCode) else {
        throw URLError(.badServerResponse)
    }
}

// ===== 闭包回调方式（旧 API）=====
func fetchUserLegacy(id: Int, completion: @escaping (Result<User, Error>) -> Void) {
    guard let url = URL(string: "https://api.example.com/users/\\(id)") else {
        completion(.failure(URLError(.badURL)))
        return
    }

    let task = URLSession.shared.dataTask(with: url) { data, response, error in
        if let error = error {
            completion(.failure(error))
            return
        }

        guard let data = data,
              let httpResponse = response as? HTTPURLResponse,
              httpResponse.statusCode == 200 else {
            completion(.failure(URLError(.badServerResponse)))
            return
        }

        do {
            let user = try JSONDecoder().decode(User.self, from: data)
            completion(.success(user))
        } catch {
            completion(.failure(error))
        }
    }
    task.resume() // 必须调用 resume 启动
}

// ===== 取消请求 =====
func fetchWithCancellation() async {
    let task = Task {
        do {
            let user = try await fetchUser(id: 1)
            print("用户: \\(user.name)")
        } catch is CancellationError {
            print("请求已取消")
        } catch {
            print("错误: \\(error)")
        }
    }

    // 一段时间后取消
    DispatchQueue.main.asyncAfter(deadline: .now() + 1) {
        task.cancel()
    }
}

// ===== 错误处理示例 =====
func demoErrorHandling() async {
    do {
        let user = try await fetchUser(id: 1)
        print("成功: \\(user.name)")
    } catch let error as URLError where error.code == .notConnectedToInternet {
        print("无网络连接")
    } catch let error as URLError where error.code == .timedOut {
        print("请求超时")
    } catch is DecodingError {
        print("JSON 解析失败")
    } catch {
        print("其他错误: \\(error.localizedDescription)")
    }
}

// ===== JSON 编解码配置 =====
func makeDecoder() -> JSONDecoder {
    let decoder = JSONDecoder()
    decoder.keyDecodingStrategy = .convertFromSnakeCase // snake_case -> camelCase
    decoder.dateDecodingStrategy = .iso8601 // ISO 8601 日期
    return decoder
}

func makeEncoder() -> JSONEncoder {
    let encoder = JSONEncoder()
    encoder.keyEncodingStrategy = .convertToSnakeCase // camelCase -> snake_case
    encoder.outputFormatting = [.prettyPrinted, .sortedKeys]
    encoder.dateEncodingStrategy = .iso8601
    return encoder
}

print("URLSession 网络请求演示完成")""",
                "tips": "URLSession.shared 是共享单例，基本请求够用，但不能自定义配置和代理；自定义会话用 URLSession(configuration:)，用完后需要 finishTasksAndInvalidate() 释放资源；data(from:) 和 data(for:) 是 Swift 5.5+ 的 async/await API，iOS 15+/macOS 12+；旧版本用 dataTask(with:completionHandler:) + resume()；URL(string:) 返回可选，构造失败返回 nil，用 guard let 处理；HTTP 响应需要转换为 HTTPURLResponse 才能访问 statusCode；状态码 2xx 成功，3xx 重定向，4xx 客户端错误，5xx 服务器错误；JSON 编解码用 JSONEncoder/JSONDecoder，模型需符合 Codable 协议；snake_case 转 camelCase 用 keyDecodingStrategy = .convertFromSnakeCase；查询参数用 URLComponents + URLQueryItem，不要手动拼字符串（自动 URL 编码）；上传文件用 uploadTask，下载用 downloadTask（自动写入临时文件）；多部分表单需要手动构造 boundary；后台下载用 background 配置 + URLSessionDownloadDelegate；请求取消用 Task.cancel() 或 URLSessionTask.cancel()；网络请求必须在 Info.plist 中配置 App Transport Security（HTTP 域名需要例外）；避免在主线程做同步网络请求（会阻塞 UI）。",
            },
            {
                "name": "Grand Central Dispatch (GCD) — 并发编程",
                "desc": "GCD 是 iOS/macOS 并发编程核心 API，基于队列（DispatchQueue）管理任务执行，支持串行/并发队列、同步/异步执行、延迟执行、调度组、信号量、屏障等，是 Swift 多线程编程的基础。",
                "functions": [
                    "DispatchQueue.main — 主队列（串行，UI 操作）",
                    "DispatchQueue.global() — 全局并发队列",
                    "DispatchQueue.global(qos:) — 指定服务质量",
                    "DispatchQueue(label:) — 创建串行队列",
                    "DispatchQueue(label:attributes:) — 创建并发队列",
                    "queue.async { } — 异步执行",
                    "queue.sync { } — 同步执行（阻塞当前线程）",
                    "queue.asyncAfter(deadline:execute:) — 延迟执行",
                    "DispatchTime.now() + .seconds(n) — 时间计算",
                    "DispatchGroup — 调度组（等待多个任务）",
                    "group.enter() / leave() — 手动管理计数",
                    "group.notify(queue:execute:) — 全部完成后通知",
                    "group.wait() — 阻塞等待全部完成",
                    "DispatchSemaphore — 信号量（限流/同步）",
                    "semaphore.wait() / signal()",
                    "DispatchWorkItem — 工作项（可取消）",
                    "workItem.cancel() / perform()",
                    "queue.async(group:execute:) — 加入调度组",
                    "DispatchQueue.concurrentPerform — 并行循环",
                    "queue.async(flags:.barrier) — 屏障任务（读写锁）",
                    "DispatchQoS — 服务质量（userInteractive/userInitiated/utility/background）",
                    "DispatchQueue.SpecificKey — 队列标识",
                    "DispatchSource — 底层事件源（定时器/文件描述符等）",
                    "DispatchSourceTimer — GCD 定时器",
                    "os_unfair_lock — 低级锁（高性能）",
                    "NSLock / NSRecursiveLock — 锁",
                    "Thread.isMainThread — 判断是否主线程",
                    "Task / Task.detached — Swift 并发（async/await）",
                    "Actor — Swift 并发数据隔离",
                ],
                "example": """import Foundation

// ===== 基本队列操作 =====
// 主队列（UI 更新必须在主线程）
DispatchQueue.main.async {
    print("在主线程执行 UI 更新")
}

// 全局并发队列（后台任务）
DispatchQueue.global().async {
    print("在后台线程执行耗时操作")
    // 完成后回主线程
    DispatchQueue.main.async {
        print("回主线程更新 UI")
    }
}

// 指定服务质量
DispatchQueue.global(qos: .userInitiated).async {
    // 用户发起的、需要立即响应的任务
}
DispatchQueue.global(qos: .background).async {
    // 后台任务，用户不可见，不紧急
}

// QoS 优先级从高到低：
// .userInteractive（动画/交互）> .userInitiated（用户等待）> .default > .utility（进度条）> .background（备份/同步）

// ===== 创建自定义队列 =====
// 串行队列（任务按顺序执行）
let serialQueue = DispatchQueue(label: "com.example.serial")
serialQueue.async { print("串行任务1") }
serialQueue.async { print("串行任务2") } // 等任务1完成后执行

// 并发队列（任务可同时执行）
let concurrentQueue = DispatchQueue(label: "com.example.concurrent", attributes: .concurrent)
concurrentQueue.async { print("并发任务1") }
concurrentQueue.async { print("并发任务2") } // 可能同时执行

// ===== 同步 vs 异步 =====
// async：不阻塞当前线程，立即返回
DispatchQueue.global().async {
    sleep(1)
    print("异步任务完成")
}
print("async 立即返回") // 先打印

// sync：阻塞当前线程，等待任务完成
// serialQueue.sync { print("同步任务") } // 会阻塞
// 注意：不要在主队列调用 sync（死锁）

// ===== 延迟执行 =====
DispatchQueue.main.asyncAfter(deadline: .now() + 2.0) {
    print("2秒后执行")
}

// 更精确的时间
let delay = DispatchTimeInterval.seconds(3)
DispatchQueue.global().asyncAfter(deadline: .now() + delay) {
    print("3秒后在后台执行")
}

// 毫秒/微秒
DispatchQueue.main.asyncAfter(deadline: .now() + .milliseconds(500)) {
    print("500毫秒后")
}

// ===== DispatchGroup 调度组 =====
// 等待多个异步任务全部完成
let group = DispatchGroup()

group.enter()
DispatchQueue.global().async {
    sleep(1)
    print("任务1完成")
    group.leave()
}

group.enter()
DispatchQueue.global().async {
    sleep(2)
    print("任务2完成")
    group.leave()
}

// 全部完成后通知（不阻塞）
group.notify(queue: .main) {
    print("所有任务完成，回主线程")
}

// 或者阻塞等待（不建议在主线程用）
// group.wait() // 阻塞当前线程直到全部完成
// print("阻塞等待完成")

// 用 async(group:) 简化
let group2 = DispatchGroup()
concurrentQueue.async(group: group2) { sleep(1); print("组任务1") }
concurrentQueue.async(group: group2) { sleep(2); print("组任务2") }
group2.notify(queue: .main) { print("组2全部完成") }

// ===== DispatchSemaphore 信号量 =====
// 限流：最多同时执行 N 个任务
let semaphore = DispatchSemaphore(value: 3) // 最多3个并发

for i in 0..<10 {
    semaphore.wait() // 信号量-1，为0则阻塞
    DispatchQueue.global().async {
        defer { semaphore.signal() } // 完成后信号量+1
        sleep(1)
        print("任务 \\(i) 完成")
    }
}

// 用信号量实现同步等待
let sem = DispatchSemaphore(value: 0)
DispatchQueue.global().async {
    sleep(1)
    print("异步操作完成")
    sem.signal()
}
sem.wait() // 阻塞直到 signal
print("继续执行")

// ===== 屏障（Barrier）—— 读写锁 =====
// 多读单写：读操作并发，写操作独占
let dataQueue = DispatchQueue(label: "com.example.data", attributes: .concurrent)
var sharedData = [String: Int]()

// 读操作（并发）
func readData(key: String) -> Int? {
    return dataQueue.sync { sharedData[key] }
}

// 写操作（屏障，独占执行）
func writeData(key: String, value: Int) {
    dataQueue.async(flags: .barrier) {
        sharedData[key] = value
    }
}

// ===== DispatchWorkItem 可取消工作项 =====
var workItem: DispatchWorkItem?

workItem = DispatchWorkItem {
    for i in 0..<10 {
        if workItem?.isCancelled ?? false {
            print("任务已取消")
            return
        }
        sleep(1)
        print("工作项执行 \\(i)")
    }
}

DispatchQueue.global().async(execute: workItem!)
// 3秒后取消
DispatchQueue.main.asyncAfter(deadline: .now() + 3) {
    workItem?.cancel()
}

// ===== concurrentPerform 并行循环 =====
// 替代 for 循环，自动并行化（适合 CPU 密集型、无依赖的循环）
DispatchQueue.concurrentPerform(iterations: 100) { i in
    // 并行执行 100 次
    let result = i * i
    if i % 10 == 0 { print("并行循环 \\(i): \\(result)") }
}

// ===== 线程安全的计数器 =====
class ThreadSafeCounter {
    private let queue = DispatchQueue(label: "com.example.counter", attributes: .concurrent)
    private var _value = 0

    var value: Int {
        queue.sync { _value } // 读：同步
    }

    func increment() {
        queue.async(flags: .barrier) { // 写：屏障
            self._value += 1
        }
    }
}

let counter = ThreadSafeCounter()
DispatchQueue.concurrentPerform(iterations: 1000) { _ in
    counter.increment()
}
print("线程安全计数器: \\(counter.value)") // 1000

// ===== 主线程检查 =====
func ensureMainThread() {
    if Thread.isMainThread {
        print("在主线程")
    } else {
        DispatchQueue.main.async { print("切到主线程") }
    }
}

// ===== GCD 定时器（比 Timer 更精确）=====
func makeGCDTimer() -> DispatchSourceTimer {
    let timer = DispatchSource.makeTimerSource(queue: .main)
    timer.schedule(deadline: .now(), repeating: 1.0) // 每秒执行
    timer.setEventHandler {
        print("GCD 定时器触发")
    }
    timer.resume() // 启动
    // timer.cancel() // 取消
    return timer
}

// ===== Swift 并发（async/await，现代方式）=====
// Task：在当前并发上下文执行
func swiftConcurrencyDemo() async {
    // Task 异步执行
    let task = Task {
        return await fetchData()
    }

    // 等待结果
    let result = await task.value
    print("Task 结果: \\(result)")

    // Task.detached：脱离当前上下文（独立优先级）
    let detached = Task.detached {
        return "detached 任务"
    }

    // async let：并行执行多个异步任务
    async let data1 = fetchData()
    async let data2 = fetchData()
    let (r1, r2) = await (data1, data2)
    print("并行结果: \\(r1), \\(r2)")

    // TaskGroup：动态数量的并行任务
    await withTaskGroup(of: String.self) { group in
        for i in 0..<5 {
            group.addTask {
                return "任务 \\(i)"
            }
        }
        for await result in group {
            print("组结果: \\(result)")
        }
    }
}

func fetchData() async -> String {
    try? await Task.sleep(nanoseconds: 1_000_000_000)
    return "数据"
}

// ===== Actor（Swift 并发数据隔离）=====
actor BankAccount {
    private(set) var balance: Double = 0

    func deposit(_ amount: Double) {
        balance += amount
    }

    func withdraw(_ amount: Double) -> Bool {
        guard balance >= amount else { return false }
        balance -= amount
        return true
    }
}

func actorDemo() async {
    let account = BankAccount()
    await account.deposit(100)
    let success = await account.withdraw(30)
    print("取款成功: \\(success), 余额: \\(await account.balance)")
}

print("GCD 并发编程演示完成")""",
                "tips": "UI 更新必须在主线程（DispatchQueue.main.async）；global() 是系统提供的并发队列，不要在上面做 sync（可能阻塞）；自定义串行队列用于保护共享资源或保证任务顺序；自定义并发队列用于并行执行独立任务；sync 会阻塞当前线程，绝不要在主队列调用 sync（死锁），也不要在同一串行队列内调用 sync（死锁）；asyncAfter 不是精确定时器，有最小精度（约1ms），精确计时用 DispatchSourceTimer；DispatchGroup 的 enter/leave 必须配对，用 async(group:) 更安全；group.notify 不阻塞，group.wait 阻塞（不要在主线程用）；信号量 wait/signal 必须配对，defer 保证 signal；屏障（barrier）只在自定义并发队列上有效，在 global 队列上无效；DispatchWorkItem 取消后需要在执行中检查 isCancelled，否则不会自动停止；concurrentPerform 是同步的，会阻塞当前线程直到所有迭代完成，适合 CPU 密集型循环；Swift 并发（async/await/Task/Actor）是现代推荐方式，GCD 用于底层控制和与旧 API 交互；Actor 自动保证数据隔离，属性和方法访问自动同步；Task 继承当前上下文的优先级和本地值，Task.detached 不继承；避免用 Thread 创建线程（GCD 和 Swift 并发更高效）。",
            },
            {
                "name": "Codable / JSONEncoder — 序列化",
                "desc": "Codable 是 Swift 编码解码协议（Encodable + Decodable），配合 JSONEncoder/JSONDecoder 实现 JSON 与 Swift 类型互转，支持自定义键映射、日期策略、嵌套类型、可选值等，是 Swift 数据序列化的标准方式。",
                "functions": [
                    "Codable — Encodable & Decodable 类型别名",
                    "Encodable — 可编码（转 JSON）",
                    "Decodable — 可解码（JSON 转模型）",
                    "JSONEncoder() — JSON 编码器",
                    "encoder.encode(value) — 编码为 Data",
                    "encoder.outputFormatting — 输出格式（.prettyPrinted/.sortedKeys）",
                    "encoder.keyEncodingStrategy — 键编码策略（.convertToSnakeCase）",
                    "encoder.dateEncodingStrategy — 日期编码策略",
                    "encoder.dataEncodingStrategy — Data 编码策略",
                    "JSONDecoder() — JSON 解码器",
                    "decoder.decode(Type.self, from: data) — 解码",
                    "decoder.keyDecodingStrategy — 键解码策略",
                    "decoder.dateDecodingStrategy — 日期解码策略",
                    "CodingKey — 自定义键映射协议",
                    "CodingKeys — 枚举指定键名",
                    "init(from decoder:) — 自定义解码",
                    "encode(to encoder:) — 自定义编码",
                    "container(keyedBy:) — 键控容器",
                    "unkeyedContainer() — 无键容器（数组）",
                    "singleValueContainer() — 单值容器",
                    "decodeIfPresent — 解码可选字段",
                    "@propertyWrapper — 属性包装器自定义编解码",
                    "JSONSerialization — 旧版 JSON 处理（NSDictionary/NSArray）",
                    "JSONSerialization.jsonObject(with:options:) — 解析为 Foundation 类型",
                    "JSONSerialization.data(withJSONObject:options:) — Foundation 类型转 JSON",
                    "PlistEncoder / PlistDecoder — plist 编解码",
                    "TopLevelEncoder / TopLevelDecoder — 编码器协议",
                ],
                "example": """import Foundation

// ===== 基本 Codable 模型 =====
struct User: Codable {
    let id: Int
    let name: String
    let email: String
    let age: Int? // 可选字段，JSON 中不存在则为 nil
    let isActive: Bool
    let createdAt: Date
}

// ===== 基本编码 =====
func encodeDemo() {
    let user = User(
        id: 1,
        name: "Alice",
        email: "alice@example.com",
        age: 25,
        isActive: true,
        createdAt: Date()
    )

    let encoder = JSONEncoder()
    encoder.outputFormatting = .prettyPrinted // 格式化输出

    do {
        let data = try encoder.encode(user)
        let jsonString = String(data: data, encoding: .utf8)!
        print("编码结果:\\n\\(jsonString)")
    } catch {
        print("编码失败: \\(error)")
    }
}

// ===== 基本解码 =====
func decodeDemo() {
    let json = \"\"\"
    {
        "id": 2,
        "name": "Bob",
        "email": "bob@example.com",
        "age": 30,
        "isActive": false,
        "createdAt": "2024-01-15T10:30:00Z"
    }
    \"\"\"

    let decoder = JSONDecoder()
    decoder.dateDecodingStrategy = .iso8601 // ISO 8601 日期

    do {
        let data = json.data(using: .utf8)!
        let user = try decoder.decode(User.self, from: data)
        print("解码结果: \\(user.name), \\(user.age ?? 0)岁")
    } catch {
        print("解码失败: \\(error)")
    }
}

// ===== CodingKeys 自定义键映射 =====
struct Person: Codable {
    let firstName: String
    let lastName: String
    let personAge: Int

    enum CodingKeys: String, CodingKey {
        case firstName = "first_name"
        case lastName = "last_name"
        case personAge = "age"
    }
}

// 自动 convertFromSnakeCase（不需要手动写 CodingKeys）
struct AutoPerson: Codable {
    let firstName: String  // JSON: first_name
    let lastName: String   // JSON: last_name
    let emailAddress: String // JSON: email_address
}

func snakeCaseDemo() {
    let json = \"\"\"
    {"first_name":"Alice","last_name":"Smith","email_address":"a@example.com"}
    \"\"\"

    let decoder = JSONDecoder()
    decoder.keyDecodingStrategy = .convertFromSnakeCase

    let person = try! decoder.decode(AutoPerson.self, from: json.data(using: .utf8)!)
    print("snake_case 解码: \\(person.firstName) \\(person.lastName)")

    // 编码为 snake_case
    let encoder = JSONEncoder()
    encoder.keyEncodingStrategy = .convertToSnakeCase
    let data = try! encoder.encode(person)
    print("snake_case 编码: \\(String(data: data, encoding: .utf8)!)")
}

// ===== 嵌套模型 =====
struct Address: Codable {
    let street: String
    let city: String
    let zipCode: String
}

struct Company: Codable {
    let name: String
    let address: Address
    let employees: [Employee]
}

struct Employee: Codable {
    let id: Int
    let name: String
    let department: String
}

func nestedDemo() {
    let company = Company(
        name: "Acme Inc",
        address: Address(street: "123 Main St", city: "Beijing", zipCode: "100000"),
        employees: [
            Employee(id: 1, name: "Alice", department: "Engineering"),
            Employee(id: 2, name: "Bob", department: "Marketing")
        ]
    )

    let encoder = JSONEncoder()
    encoder.outputFormatting = .prettyPrinted
    let data = try! encoder.encode(company)
    print("嵌套模型:\\n\\(String(data: data, encoding: .utf8)!)")
}

// ===== 自定义编解码（init(from:) / encode(to:)）=====
struct Coordinate: Codable {
    let latitude: Double
    let longitude: Double

    // JSON 格式: {"lat": 39.9, "lng": 116.4}
    enum CodingKeys: String, CodingKey {
        case latitude = "lat"
        case longitude = "lng"
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        latitude = try container.decode(Double.self, forKey: .latitude)
        longitude = try container.decode(Double.self, forKey: .longitude)
    }

    func encode(to encoder: Encoder) throws {
        var container = encoder.container(keyedBy: CodingKeys.self)
        try container.encode(latitude, forKey: .latitude)
        try container.encode(longitude, forKey: .longitude)
    }
}

// 更复杂的自定义：多态类型
enum VehicleType: String, Codable {
    case car, motorcycle, truck
}

class Vehicle: Codable {
    let type: VehicleType
    let brand: String

    init(type: VehicleType, brand: String) {
        self.type = type
        self.brand = brand
    }
}

class Car: Vehicle {
    let doors: Int

    init(brand: String, doors: Int) {
        self.doors = doors
        super.init(type: .car, brand: brand)
    }

    enum CodingKeys: String, CodingKey { case doors }

    required init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        doors = try container.decode(Int.self, forKey: .doors)
        try super.init(from: decoder)
    }

    override func encode(to encoder: Encoder) throws {
        try super.encode(to: encoder)
        var container = encoder.container(keyedBy: CodingKeys.self)
        try container.encode(doors, forKey: .doors)
    }
}

// ===== 自定义日期格式 =====
struct Event: Codable {
    let title: String
    let date: Date

    enum CodingKeys: String, CodingKey { case title, date }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        title = try container.decode(String.self, forKey: .title)

        // 自定义日期格式 "yyyy-MM-dd"
        let dateString = try container.decode(String.self, forKey: .date)
        let formatter = DateFormatter()
        formatter.dateFormat = "yyyy-MM-dd"
        guard let date = formatter.date(from: dateString) else {
            throw DecodingError.dataCorruptedError(forKey: .date, in: container,
                debugDescription: "日期格式错误")
        }
        self.date = date
    }

    func encode(to encoder: Encoder) throws {
        var container = encoder.container(keyedBy: CodingKeys.self)
        try container.encode(title, forKey: .title)
        let formatter = DateFormatter()
        formatter.dateFormat = "yyyy-MM-dd"
        try container.encode(formatter.string(from: date), forKey: .date)
    }
}

// ===== 枚举编解码 =====
enum Direction: String, Codable {
    case north, south, east, west
    // JSON: "north" / "south" / "east" / "west"
}

enum Status: Int, Codable {
    case pending = 0
    case active = 1
    case archived = 2
    // JSON: 0 / 1 / 2
}

// ===== 数组和字典 =====
func collectionsDemo() {
    // 数组
    let numbers = [1, 2, 3, 4, 5]
    let data = try! JSONEncoder().encode(numbers)
    print("数组 JSON: \\(String(data: data, encoding: .utf8)!)")

    // 字典
    let dict = ["apple": 5, "banana": 3, "orange": 8]
    let dictData = try! JSONEncoder().encode(dict)
    print("字典 JSON: \\(String(data: dictData, encoding: .utf8)!)")

    // 解码数组
    let jsonArray = "[1,2,3,4,5]"
    let decodedArray = try! JSONDecoder().decode([Int].self, from: jsonArray.data(using: .utf8)!)
    print("解码数组: \\(decodedArray)")
}

// ===== JSONSerialization（旧方式，处理动态 JSON）=====
func jsonSerializationDemo() {
    // 解析为 NSDictionary/NSArray
    let json = \"\"\"
    {"name":"Alice","scores":[95,87,92],"metadata":{"level":5}}
    \"\"\"

    if let data = json.data(using: .utf8),
       let dict = try? JSONSerialization.jsonObject(with: data) as? [String: Any] {
        print("name: \\(dict["name"] ?? "")")
        if let scores = dict["scores"] as? [Int] {
            print("scores: \\(scores)")
        }
        if let metadata = dict["metadata"] as? [String: Any],
           let level = metadata["level"] as? Int {
            print("level: \\(level)")
        }
    }

    // 从 Foundation 类型生成 JSON
    let obj: [String: Any] = [
        "name": "Bob",
        "age": 30,
        "skills": ["Swift", "Objective-C"]
    ]
    if let jsonData = try? JSONSerialization.data(withJSONObject: obj, options: .prettyPrinted),
       let jsonStr = String(data: jsonData, encoding: .utf8) {
        print("生成 JSON:\\n\\(jsonStr)")
    }
}

// ===== 错误处理 =====
func errorHandlingDemo() {
    let invalidJSON = "{invalid}"

    do {
        let _ = try JSONDecoder().decode(User.self, from: invalidJSON.data(using: .utf8)!)
    } catch let error as DecodingError {
        switch error {
        case .keyNotFound(let key, let context):
            print("缺少键: \\(key.stringValue), 路径: \\(context.codingPath)")
        case .valueNotFound(let type, let context):
            print("值为空: \\(type), 路径: \\(context.codingPath)")
        case .typeMismatch(let type, let context):
            print("类型不匹配: 期望 \\(type), 路径: \\(context.codingPath)")
        case .dataCorrupted(let context):
            print("数据损坏: \\(context.debugDescription)")
        @unknown default:
            print("未知解码错误")
        }
    } catch {
        print("其他错误: \\(error)")
    }
}

// ===== 属性包装器自定义编解码 =====
@propertyWrapper
struct ISO8601Date: Codable {
    var wrappedValue: Date

    init(wrappedValue: Date) {
        self.wrappedValue = wrappedValue
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.singleValueContainer()
        let string = try container.decode(String.self)
        guard let date = ISO8601DateFormatter().date(from: string) else {
            throw DecodingError.dataCorruptedError(in: container,
                debugDescription: "无效的 ISO8601 日期")
        }
        wrappedValue = date
    }

    func encode(to encoder: Encoder) throws {
        var container = encoder.singleValueContainer()
        try container.encode(ISO8601DateFormatter().string(from: wrappedValue))
    }
}

struct Post: Codable {
    let title: String
    @ISO8601Date var publishedAt: Date
}

// 运行所有演示
encodeDemo()
decodeDemo()
snakeCaseDemo()
nestedDemo()
collectionsDemo()
jsonSerializationDemo()
errorHandlingDemo()

print("Codable 序列化演示完成")""",
                "tips": "Codable = Encodable + Decodable，大部分情况只需声明 Codable 即可自动合成编解码；属性必须全部是 Codable 类型才能自动合成；可选属性（Int?）在 JSON 中不存在时解码为 nil，非可选属性缺失会抛 DecodingError；CodingKeys 枚举用于自定义键名或排除某些属性；keyDecodingStrategy = .convertFromSnakeCase 自动将 snake_case 转为 camelCase，不需要手动写 CodingKeys；日期默认编码为时间戳（Double），用 .iso8601 或 .formatted/自定义策略；嵌套模型自动递归编解码；自定义 init(from:) 和 encode(to:) 用于特殊格式、计算属性、多态类型；多态类型（class 继承）需要手动编解码，用 type 字段区分子类；枚举遵守 String/Int 等 RawRepresentable 可自动编解码；JSONSerialization 用于动态 JSON（结构不确定），返回 [String: Any]/[Any]，需手动类型转换；Codable 性能优于 JSONSerialization，类型安全；解码错误用 DecodingError 的关联值获取详细信息（缺哪个键、路径等）；Data 类型默认编码为 base64 字符串；属性包装器（@propertyWrapper）可封装自定义编解码逻辑，复用性强；PlistEncoder/PlistDecoder 用于 plist 格式；TopLevelEncoder/TopLevelDecoder 协议用于泛型编码器。",
            },
        ],
    }

_more6 = _more_modules6()
for _k, _v in _more6.items():
    if _k not in LANG_MODULES:
        LANG_MODULES[_k] = _v
del _more6, _more_modules6


def _more_modules7():
    return {
        "kotlin": [
            {
                "name": "kotlin.collections — 集合类型",
                "desc": "Kotlin 标准库集合类型：List（只读/可变）、Set、Map，支持丰富的高阶函数（map/filter/fold/groupBy 等），区分只读和可变集合，是 Kotlin 函数式编程的核心。",
                "functions": [
                    "listOf(...) — 只读 List",
                    "mutableListOf(...) — 可变 List",
                    "arrayListOf(...) — ArrayList",
                    "setOf(...) / mutableSetOf(...) / hashSetOf / linkedSetOf / sortedSetOf",
                    "mapOf(...) / mutableMapOf(...) / hashMapOf / linkedMapOf / sortedMapOf",
                    "list.size / isEmpty() / isNotEmpty()",
                    "list[i] / getOrNull(i) / getOrElse(i) { default }",
                    "list.first() / last() / firstOrNull() / lastOrNull()",
                    "list.first { predicate } / find { } / findLast { }",
                    "list.contains(x) / in 运算符",
                    "list.indexOf(x) / lastIndexOf(x) / indexOfFirst { }",
                    "list.map { } / mapIndexed { } / mapNotNull { }",
                    "list.filter { } / filterNot { } / filterNotNull / filterIsInstance",
                    "list.fold(initial) { acc, x -> } / reduce { }",
                    "list.groupBy { } / groupingBy { } / eachCount()",
                    "list.sorted() / sortedBy { } / sortedDescending / sortedByDescending",
                    "list.reversed() / shuffled() / distinct() / distinctBy { }",
                    "list.flatMap { } / flatten()",
                    "list.chunked(n) / windowed(size, step)",
                    "list.zip(other) / unzip()",
                    "list.partition { } — 分为满足/不满足两个列表",
                    "list.any { } / all { } / none { } / count { }",
                    "list.sum() / average() / max() / min() / maxBy { } / minBy { }",
                    "list.associate { } / associateBy { } / associateWith { }",
                    "list.forEach { } / forEachIndexed { }",
                    "list.take(n) / takeLast(n) / takeWhile { } / drop(n)",
                    "list.slice(range) / subList(from, to)",
                    "list.toList() / toSet() / toMap() / toTypedArray()",
                    "mutableList.add(x) / addAll / remove(x) / removeAt(i) / clear()",
                    "mutableList += x / -= x — 运算符重载",
                    "map[key] / map.getOrDefault(key, default) / map.getValue(key)",
                    "map.keys / map.values / map.entries",
                    "map.mapValues { } / mapKeys { } / filterKeys / filterValues",
                    "mutableMap[key] = value / put / remove / clear",
                    "sequenceOf(...) — 惰性序列（Sequence）",
                    "list.asSequence() — 转序列（惰性求值）",
                    "buildList { } / buildMap { } — 构建器",
                ],
                "example": """// ===== List 列表 =====
val readOnly = listOf(1, 2, 3, 4, 5) // 只读
val mutable = mutableListOf(1, 2, 3) // 可变
val arrayList = arrayListOf("a", "b", "c")

// 可变操作
mutable.add(4)
mutable.addAll(listOf(5, 6))
mutable.remove(1)
mutable.removeAt(0)
mutable[0] = 100
mutable += 7
mutable -= 100
// mutable.clear()

// 访问
println("第一个: ${readOnly.first()}")
println("最后一个: ${readOnly.last()}")
println("索引2: ${readOnly[2]}")
println("安全访问: ${readOnly.getOrNull(10)}") // null
println("默认值: ${readOnly.getOrElse(10) { -1 }}") // -1

// 查找
val even = readOnly.find { it % 2 == 0 } // 2
val lastEven = readOnly.findLast { it % 2 == 0 } // 4
val index = readOnly.indexOf(3) // 2
val firstIndex = readOnly.indexOfFirst { it > 3 } // 3

// ===== 高阶函数 =====
val numbers = listOf(1, 2, 3, 4, 5, 6, 7, 8, 9, 10)

// map 映射
val doubled = numbers.map { it * 2 }
val withIndex = numbers.mapIndexed { index, value -> index * value }
val notNull = listOf("1", "2", "three", "4").mapNotNull { it.toIntOrNull() } // [1,2,4]

// filter 过滤
val evens = numbers.filter { it % 2 == 0 }
val odds = numbers.filterNot { it % 2 == 0 }
val positive = listOf(1, -2, 3, null, -5).filterNotNull() // [1,-2,3,-5]
val stringsOnly = listOf(1, "a", 2, "b").filterIsInstance<String>() // ["a","b"]

// fold / reduce 归约
val sum = numbers.fold(0) { acc, i -> acc + i } // 55
val product = numbers.reduce { acc, i -> acc * i } // 3628800
val concatenated = listOf("a", "b", "c").fold("") { acc, s -> acc + s } // "abc"

// groupBy 分组
val words = listOf("apple", "banana", "cherry", "avocado", "blueberry")
val byFirstLetter = words.groupBy { it.first() }
// {a=[apple, avocado], b=[banana, blueberry], c=[cherry]}

val byLength = words.groupBy { it.length }
// {5=[apple], 6=[banana, cherry], 7=[avocado, blueberry]}

// groupingBy + eachCount 统计频次
val freq = words.groupingBy { it.first() }.eachCount()
// {a=2, b=2, c=1}

// 排序
val sortedAsc = numbers.sorted()
val sortedDesc = numbers.sortedDescending()
val sortedByLength = words.sortedBy { it.length }
val sortedByLengthDesc = words.sortedByDescending { it.length }

// 去重
val withDup = listOf(1, 2, 2, 3, 3, 3, 4)
val unique = withDup.distinct() // [1,2,3,4]
val uniqueBy = listOf("a" to 1, "b" to 1, "c" to 2).distinctBy { it.second } // [(a,1),(c,2)]

// flatMap 扁平化
val nested = listOf(listOf(1, 2), listOf(3, 4), listOf(5, 6))
val flattened = nested.flatten() // [1,2,3,4,5,6]
val flatMapped = nested.flatMap { list -> list.map { it * 10 } } // [10,20,30,40,50,60]

// 分块与窗口
val chunks = numbers.chunked(3) // [[1,2,3],[4,5,6],[7,8,9],[10]]
val windows = numbers.windowed(3, 1) // [[1,2,3],[2,3,4],...,[8,9,10]]
val sliding = numbers.windowed(3, 2, partialWindows = true)

// 分区
val (evenList, oddList) = numbers.partition { it % 2 == 0 }
// evenList=[2,4,6,8,10], oddList=[1,3,5,7,9]

// 聚合
val total = numbers.sum()
val avg = numbers.average()
val maxVal = numbers.maxOrNull()
val minVal = numbers.minOrNull()
val maxBy = words.maxByOrNull { it.length }
val count = numbers.count { it > 5 }

// 布尔判断
val anyGreater = numbers.any { it > 10 } // false
val allPositive = numbers.all { it > 0 } // true
val noneZero = numbers.none { it == 0 } // true

// 取/跳过
val first3 = numbers.take(3) // [1,2,3]
val last3 = numbers.takeLast(3) // [8,9,10]
val whileLess5 = numbers.takeWhile { it < 5 } // [1,2,3,4]
val drop3 = numbers.drop(3) // [4,5,6,7,8,9,10]
val dropWhile = numbers.dropWhile { it < 5 } // [5,6,7,8,9,10]

// 转集合
val toSet = numbers.toSet()
val toMutable = numbers.toMutableList()
val toTypedArray = numbers.toTypedArray()

// ===== Map 字典 =====
val readOnlyMap = mapOf("a" to 1, "b" to 2, "c" to 3)
val mutableMap = mutableMapOf("x" to 10, "y" to 20)
val hashMap = hashMapOf("k1" to "v1", "k2" to "v2")
val sortedMap = sortedMapOf("b" to 2, "a" to 1, "c" to 3) // 按 key 排序

// 访问
println(readOnlyMap["a"]) // 1
println(readOnlyMap.getOrDefault("z", 0)) // 0
println(readOnlyMap.getValue("a")) // 1（不存在抛异常）
println(readOnlyMap.keys) // [a, b, c]
println(readOnlyMap.values) // [1, 2, 3]

// 可变操作
mutableMap["z"] = 30
mutableMap.put("w", 40)
mutableMap.remove("x")
mutableMap += "v" to 50
mutableMap -= "y"

// 遍历
for ((key, value) in readOnlyMap) {
    println("$key -> $value")
}
readOnlyMap.forEach { (key, value) -> println("$key: $value") }

// map 高阶函数
val doubledMap = readOnlyMap.mapValues { it.value * 2 }
val upperKeys = readOnlyMap.mapKeys { it.key.uppercase() }
val filteredMap = readOnlyMap.filterKeys { it > "a" }
val filteredValues = readOnlyMap.filterValues { it > 1 }

// associate 从列表构建 map
val lengthMap = words.associateWith { it.length }
// {apple=5, banana=6, ...}
val byFirst = words.associateBy { it.first() }
// 注意：key 重复会覆盖
val pairs = words.associate { it to it.length }

// ===== Set 集合 =====
val set = setOf(1, 2, 3, 3, 3) // {1,2,3}
val mutableSet = mutableSetOf(1, 2, 3)
mutableSet.add(4)
mutableSet.remove(1)

val setA = setOf(1, 2, 3, 4)
val setB = setOf(3, 4, 5, 6)
println("并集: ${setA union setB}") // [1,2,3,4,5,6]
println("交集: ${setA intersect setB}") // [3,4]
println("差集: ${setA subtract setB}") // [1,2]

// ===== Sequence 惰性序列 =====
val sequence = numbers.asSequence()
    .filter { it % 2 == 0 }
    .map { it * it }
    .take(3)
    .toList() // 终端操作才触发计算
// [4, 16, 36]

val lazySeq = sequence {
    yield(1)
    yieldAll(listOf(2, 3))
    yield(4)
}

// ===== buildList / buildMap 构建器 =====
val built = buildList {
    add(1)
    addAll(listOf(2, 3))
    add(4)
} // [1,2,3,4]

val builtMap = buildMap {
    put("a", 1)
    put("b", 2)
}

// ===== 范围 =====
val range = 1..10 // 闭区间
val untilRange = 1 until 10 // 半开区间
val downTo = 10 downTo 1 // 倒序
val step = 1..10 step 2 // 步长2
val charRange = 'a'..'z'

for (i in 1..5) print(i) // 12345
println()
(1..5).forEach { print(it) } // 12345
println()

println("集合类型演示完成")""",
                "tips": "Kotlin 集合默认只读，可变集合用 MutableList/MutableSet/MutableMap；只读集合不是不可变的，可能被其他引用修改（Kotlin 没有真正的不可变集合）；listOf 返回的是只读视图，底层可能是可变的；高阶函数不修改原集合，返回新集合；Sequence 是惰性求值，适合大数据量和链式操作，避免中间集合分配；fold 有初始值，reduce 没有（空集合抛异常）；groupBy 返回 Map<K, List<T>>，groupingBy + eachCount 用于统计频次；sortedBy 按选择器排序，sortedByDescending 降序；distinctBy 按选择器去重；chunked 分块，windowed 滑动窗口（partialWindows=true 包含不完整窗口）；partition 返回 Pair<List, List>，解构赋值；associateWith/associateBy 从集合构建 Map，key 重复会覆盖；Map 的 [] 访问返回可空类型，用 getOrDefault 或 getValue；in 运算符用于 contains 判断；+= / -= 运算符对可变集合有效；buildList/buildMap 是 Kotlin 1.6+ 的构建器函数，高效构建集合；范围 1..10 包含两端，1 until 10 不包含右端；downTo 倒序，step 步长；数组用 Array/IntArray 等，与 List 不同（数组是可变且固定大小）。",
            },
            {
                "name": "kotlin.io / java.io — 文件与IO",
                "desc": "Kotlin 提供简洁的文件 IO 扩展函数（readText/writeText/forEachLine 等），同时兼容 Java IO 类（File/InputStream/Reader/BufferedReader），支持文本和二进制文件操作。",
                "functions": [
                    "File(path) — 创建文件对象",
                    "file.readText() — 读取整个文件为字符串",
                    "file.writeText(text) — 写入字符串（覆盖）",
                    "file.appendText(text) — 追加文本",
                    "file.readLines() — 读取为行列表",
                    "file.forEachLine { line -> } — 逐行处理",
                    "file.useLines { lines -> } — 使用行序列",
                    "file.readBytes() / writeBytes(bytes)",
                    "file.inputStream() / outputStream() / bufferedReader() / bufferedWriter()",
                    "file.printWriter() — PrintWriter",
                    "file.exists() / isFile / isDirectory / canRead / canWrite",
                    "file.name / path / absolutePath / parent / extension",
                    "file.length() / lastModified()",
                    "file.mkdir() / mkdirs() / createNewFile()",
                    "file.delete() / deleteRecursively()",
                    "file.renameTo(target) / copyTo(target, overwrite)",
                    "file.walk() / walkTopDown() / walkBottomUp() — 遍历目录树",
                    "file.listFiles() / listFiles { filter }",
                    "file.resolve(child) — 拼接路径",
                    "File(path).bufferedReader().use { } — 自动关闭",
                    "use { } — AutoCloseable 扩展，自动关闭",
                    "reader.readText() / readLines() / forEachLine()",
                    "writer.write(text) / append(text)",
                    "InputStream.reader() / buffered()",
                    "OutputStream.writer() / buffered()",
                    "println / print — 标准输出",
                    "readLine() — 读取标准输入一行",
                    "Scanner — 扫描输入",
                    "File.separator — 路径分隔符",
                    "kotlin.io.path — 路径操作（Kotlin 1.8+）",
                    "java.nio.file.Files / Paths — NIO 文件操作",
                ],
                "example": """import java.io.File
import java.io.PrintWriter
import java.util.Scanner

// ===== 简单文件读写 =====
fun simpleReadWrite() {
    val file = File("test.txt")

    // 写入（覆盖）
    file.writeText("Hello, World!\\n第二行\\n第三行\\n")

    // 读取整个文件
    val content = file.readText()
    println("文件内容:\\n$content")

    // 追加
    file.appendText("追加的一行\\n")

    // 读取为行列表
    val lines = file.readLines()
    lines.forEachIndexed { index, line ->
        println("行${index + 1}: $line")
    }

    // 逐行处理（不加载全部到内存）
    file.forEachLine { line ->
        if (line.contains("第")) {
            println("匹配: $line")
        }
    }

    // 使用行序列（惰性）
    file.useLines { lines ->
        val firstMatch = lines.firstOrNull { it.length > 5 }
        println("第一个长行: $firstMatch")
    }
}

// ===== 二进制文件 =====
fun binaryFile() {
    val file = File("binary.dat")

    // 写入字节
    val data = byteArrayOf(0x48, 0x65, 0x6C, 0x6C, 0x6F) // "Hello"
    file.writeBytes(data)

    // 读取字节
    val readData = file.readBytes()
    println("读取 ${readData.size} 字节")
    println("内容: ${String(readData)}")

    // 追加字节
    file.appendBytes(byteArrayOf(0x21)) // "!"
}

// ===== 流操作（use 自动关闭）=====
fun streamOperations() {
    val file = File("stream.txt")

    // BufferedReader 读取
    file.bufferedReader().use { reader ->
        val line = reader.readLine()
        println("第一行: $line")
        val rest = reader.readText()
        println("剩余: $rest")
    } // 自动关闭

    // BufferedWriter 写入
    file.bufferedWriter().use { writer ->
        writer.write("第一行\\n")
        writer.write("第二行\\n")
        writer.newLine()
        writer.write("第三行")
    }

    // PrintWriter
    file.printWriter().use { out ->
        out.println("PrintWriter 第一行")
        out.printf("格式化: %d, %.2f\\n", 42, 3.14)
    }

    // InputStream / OutputStream
    file.outputStream().use { output ->
        output.write("Hello Stream".toByteArray())
    }

    file.inputStream().use { input ->
        val bytes = input.readBytes()
        println("InputStream 读取: ${String(bytes)}")
    }

    // 复制文件
    val source = File("stream.txt")
    val dest = File("copy.txt")
    source.copyTo(dest, overwrite = true)

    // 流式复制
    source.inputStream().use { input ->
        dest.outputStream().use { output ->
            input.copyTo(output)
        }
    }
}

// ===== 文件信息与操作 =====
fun fileInfo() {
    val file = File("test.txt")

    println("存在: ${file.exists()}")
    println("是文件: ${file.isFile}")
    println("是目录: ${file.isDirectory}")
    println("可读: ${file.canRead()}")
    println("可写: ${file.canWrite()}")
    println("文件名: ${file.name}")
    println("扩展名: ${file.extension}")
    println("无扩展名: ${file.nameWithoutExtension}")
    println("路径: ${file.path}")
    println("绝对路径: ${file.absolutePath}")
    println("父目录: ${file.parent}")
    println("大小: ${file.length()} bytes")
    println("最后修改: ${file.lastModified()}")

    // 目录操作
    val dir = File("mydir")
    dir.mkdir() // 创建单级目录
    File("path/to/dir").mkdirs() // 递归创建

    // 列出目录
    val files = dir.listFiles()
    files?.forEach { f ->
        println("  ${f.name} (${f.length()} bytes)")
    }

    // 过滤列出
    val txtFiles = dir.listFiles { f -> f.extension == "txt" }

    // 重命名
    file.renameTo(File("renamed.txt"))

    // 删除
    File("renamed.txt").delete()
    dir.delete() // 只能删空目录
    File("path").deleteRecursively() // 递归删除
}

// ===== 遍历目录树 =====
fun walkDirectory() {
    val root = File(".")

    // 从上到下遍历
    root.walkTopDown().forEach { file ->
        if (file.extension == "kt") {
            println("Kotlin 文件: ${file.relativeTo(root)}")
        }
    }

    // 从下到上遍历
    root.walkBottomUp().forEach { file ->
        // 处理
    }

    // 带过滤的遍历
    root.walk()
        .filter { it.isFile }
        .filter { it.extension in listOf("txt", "md") }
        .maxDepth(3)
        .forEach { println("找到: ${it.name}") }

    // 统计目录大小
    val totalSize = root.walk()
        .filter { it.isFile }
        .sumOf { it.length() }
    println("目录总大小: $totalSize bytes")
}

// ===== 路径拼接 =====
fun pathOperations() {
    val base = File("/home/user")
    val child = base.resolve("documents/file.txt")
    println("拼接路径: ${child.path}") // /home/user/documents/file.txt

    // 相对路径
    val file = File("/home/user/documents/file.txt")
    val relative = file.relativeTo(File("/home/user"))
    println("相对路径: ${relative.path}") // documents/file.txt

    // 规范化路径
    println("规范化: ${File("path/../file.txt").canonicalPath}")
}

// ===== 标准输入输出 =====
fun standardIO() {
    // 输出
    println("Hello, World!")
    print("不换行")
    println("继续")

    // 格式化输出
    printf("整数: %d, 浮点数: %.2f, 字符串: %s%n", 42, 3.14, "hello")

    // 读取输入
    print("输入你的名字: ")
    val name = readLine() ?: "匿名"
    println("你好, $name!")

    // Scanner 读取
    val scanner = Scanner(System.`in`)
    print("输入年龄: ")
    val age = scanner.nextInt()
    println("年龄: $age")

    // 从字符串扫描
    val strScanner = Scanner("10 20 30")
    while (strScanner.hasNextInt()) {
        print("${strScanner.nextInt()} ")
    }
    println()
}

// ===== 临时文件 =====
fun tempFiles() {
    // 创建临时文件
    val temp = File.createTempFile("prefix_", ".tmp")
    println("临时文件: ${temp.absolutePath}")
    temp.writeText("临时内容")
    temp.deleteOnExit() // JVM 退出时删除

    // 临时目录
    val tempDir = File.createTempFile("dir_", "").apply {
        delete()
        mkdir()
    }
    println("临时目录: ${tempDir.absolutePath}")
}

// ===== Java NIO 互操作 =====
fun nioInterop() {
    // Kotlin 可以直接使用 Java NIO
    val path = java.nio.file.Paths.get("nio.txt")
    java.nio.file.Files.writeString(path, "NIO 写入")
    val content = java.nio.file.Files.readString(path)
    println("NIO 读取: $content")

    // Kotlin 1.8+ 的 kotlin.io.path 扩展
    // import kotlin.io.path.*
    // path.writeText("hello")
    // path.readText()
    // path.listDirectoryEntries()
}

// 运行演示
simpleReadWrite()
binaryFile()
streamOperations()
fileInfo()
walkDirectory()
pathOperations()
standardIO()
tempFiles()
nioInterop()

// 清理
File("test.txt").delete()
File("binary.dat").delete()
File("stream.txt").delete()
File("copy.txt").delete()
File("nio.txt").delete()

println("文件 IO 演示完成")""",
                "tips": "Kotlin 的 File 扩展函数（readText/writeText/forEachLine）比 Java 简洁很多；readText/readLines 会一次性读入内存，大文件用 forEachLine/useLines 流式处理；use { } 是 AutoCloseable 的扩展函数，自动关闭资源（相当于 Java 的 try-with-resources）；bufferedReader/bufferedWriter 返回缓冲流，性能更好；writeText 覆盖文件，appendText 追加；copyTo 默认不覆盖已存在文件，overwrite=true 才覆盖；deleteRecursively 递归删除目录，慎用；walk/walkTopDown/walkBottomUp 返回 FileTreeWalk 序列，可链式过滤；resolve 拼接路径，relativeTo 计算相对路径；readLine() 从标准输入读取一行，返回可空字符串；Scanner 用于解析基本类型，nextInt/nextDouble 等；临时文件用 createTempFile，deleteOnExit 退出时删除；Kotlin 1.8+ 有 kotlin.io.path 扩展，更现代；文件编码默认 UTF-8，可指定 Charsets.UTF_16 等；大文件复制用 inputStream.copyTo(outputStream) 流式复制；路径分隔符用 File.separator 或 resolve，不要手动拼字符串。",
            },
            {
                "name": "kotlinx.coroutines — 协程与异步",
                "desc": "kotlinx.coroutines 是 Kotlin 官方异步编程库，提供协程（Coroutine）、挂起函数（suspend）、调度器（Dispatcher）、作用域（Scope）、通道（Channel）、流（Flow）、异步/等待（async/await）等，是 Kotlin 并发编程的核心。",
                "functions": [
                    "GlobalScope.launch { } — 启动协程（不推荐，生命周期不受控）",
                    "CoroutineScope(Dispatchers.Default).launch { } — 自定义作用域",
                    "runBlocking { } — 阻塞当前线程运行协程（测试/主函数用）",
                    "suspend fun — 挂起函数",
                    "delay(ms) — 非阻塞延迟",
                    "Dispatchers.Default — CPU 密集型调度器",
                    "Dispatchers.IO — IO 密集型调度器",
                    "Dispatchers.Main — 主线程（Android/UI）",
                    "Dispatchers.Unconfined — 不受限调度器",
                    "withContext(Dispatchers.IO) { } — 切换上下文",
                    "async { } — 启动异步任务，返回 Deferred<T>",
                    "deferred.await() — 等待异步结果",
                    "coroutineScope { } — 新建协程作用域（子协程失败取消所有）",
                    "supervisorScope { } — 监督作用域（子协程失败不影响其他）",
                    "Job — 协程任务句柄",
                    "job.cancel() / job.join() / job.cancelAndJoin()",
                    "CoroutineExceptionHandler — 异常处理器",
                    "Channel<T> — 通道（协程间通信）",
                    "channel.send(x) / channel.receive()",
                    "Channel.close() — 关闭通道",
                    "produce { } — 生产通道",
                    "actor { } — 演员模式（已废弃，用 StateFlow）",
                    "Flow<T> — 冷流（异步数据流）",
                    "flow { emit(x) } — 构建流",
                    "flow.collect { } — 收集流",
                    "flow.map / filter / transform — 流操作符",
                    "flowOn(Dispatchers.IO) — 切换流上下文",
                    "flow.buffer / conflate / collectLatest — 背压处理",
                    "StateFlow — 状态流（热流，有当前值）",
                    "SharedFlow — 共享流（热流，多订阅者）",
                    "MutableStateFlow — 可变状态流",
                    "select — 多路复用（选择第一个完成的）",
                    "mutex — 互斥锁",
                    "Semaphore — 信号量",
                    "CancellationException — 取消异常",
                    "ensureActive() — 检查协程是否活跃",
                    "yield() — 让出线程",
                    "TimeoutCancellationException — 超时异常",
                    "withTimeout(ms) { } — 超时取消",
                    "withTimeoutOrNull(ms) { } — 超时返回 null",
                ],
                "example": """import kotlinx.coroutines.*
import kotlinx.coroutines.flow.*
import kotlinx.coroutines.channels.*
import kotlin.system.measureTimeMillis

// ===== 基本协程 =====
fun basicCoroutine() = runBlocking {
    // launch 启动协程（不阻塞）
    launch {
        delay(1000)
        println("协程1完成")
    }

    launch {
        delay(500)
        println("协程2完成")
    }

    println("主协程继续")
    // runBlocking 等待所有子协程完成
}

// ===== 挂起函数 =====
suspend fun fetchData(): String {
    delay(500) // 模拟网络请求
    return "数据"
}

suspend fun processData(input: String): String {
    delay(300)
    return input.uppercase()
}

fun suspendDemo() = runBlocking {
    val result = fetchData()
    val processed = processData(result)
    println("结果: $processed")
}

// ===== async/await 并行 =====
fun asyncAwaitDemo() = runBlocking {
    val time = measureTimeMillis {
        val deferred1 = async { fetchData() }
        val deferred2 = async { processData("hello") }

        // 并行等待两个结果
        val result1 = deferred1.await()
        val result2 = deferred2.await()
        println("结果1: $result1, 结果2: $result2")
    }
    println("并行耗时: ${time}ms") // 约500ms（不是800ms）

    // async 结构化并发
    coroutineScope {
        val d1 = async { fetchData() }
        val d2 = async { processData("test") }
        println("${d1.await()} - ${d2.await()}")
    }
}

// ===== 调度器与上下文切换 =====
fun dispatcherDemo() = runBlocking {
    // Default：CPU 密集型
    launch(Dispatchers.Default) {
        println("Default 线程: ${Thread.currentThread().name}")
        // 计算密集型操作
    }

    // IO：IO 密集型
    launch(Dispatchers.IO) {
        println("IO 线程: ${Thread.currentThread().name}")
        // 网络/文件操作
    }

    // withContext 切换上下文
    val result = withContext(Dispatchers.IO) {
        // 在 IO 线程执行
        fetchData()
    }
    println("回到原上下文: $result")

    // 自定义协程作用域
    val scope = CoroutineScope(Dispatchers.Default + SupervisorJob())
    scope.launch {
        println("自定义作用域协程")
    }
    delay(100)
    scope.cancel() // 取消作用域内所有协程
}

// ===== 取消与超时 =====
fun cancellationDemo() = runBlocking {
    // 取消协程
    val job = launch {
        repeat(10) { i ->
            println("执行 $i")
            delay(200) // delay 是可取消的
        }
    }
    delay(500)
    job.cancel() // 取消
    job.join()   // 等待取消完成
    println("已取消")

    // cancelAndJoin 合并
    val job2 = launch {
        repeat(10) {
            delay(100)
        }
    }
    delay(200)
    job2.cancelAndJoin()

    // CPU 密集型协程需要检查取消状态
    val job3 = launch(Dispatchers.Default) {
        for (i in 0..1000000) {
            ensureActive() // 检查是否被取消
            // 或 yield()
        }
    }
    job3.cancelAndJoin()

    // 超时
    try {
        withTimeout(500) {
            delay(1000) // 会超时
        }
    } catch (e: TimeoutCancellationException) {
        println("超时了")
    }

    // 超时返回 null（不抛异常）
    val result = withTimeoutOrNull(500) {
        delay(1000)
        "完成"
    }
    println("超时结果: $result") // null
}

// ===== 异常处理 =====
fun exceptionDemo() = runBlocking {
    // CoroutineExceptionHandler
    val handler = CoroutineExceptionHandler { _, exception ->
        println("捕获异常: ${exception.message}")
    }

    val scope = CoroutineScope(SupervisorJob() + handler)

    // supervisorScope：子协程失败不影响其他
    supervisorScope {
        launch {
            delay(100)
            throw RuntimeException("协程1失败")
        }
        launch {
            delay(200)
            println("协程2正常完成")
        }
    }

    // async 的异常在 await 时抛出
    val deferred = async {
        throw RuntimeException("async 失败")
    }
    try {
        deferred.await()
    } catch (e: Exception) {
        println("await 捕获: ${e.message}")
    }
}

// ===== Channel 通道 =====
fun channelDemo() = runBlocking {
    val channel = Channel<Int>()

    // 生产者
    launch {
        for (i in 1..5) {
            channel.send(i) // 发送（缓冲区满时挂起）
            println("发送: $i")
        }
        channel.close() // 关闭通道
    }

    // 消费者
    launch {
        for (value in channel) { // 遍历直到通道关闭
            println("接收: $value")
        }
    }

    delay(1000)

    // 带缓冲的通道
    val buffered = Channel<Int>(capacity = 3)
    launch {
        repeat(5) { buffered.send(it) }
        buffered.close()
    }
    buffered.consumeEach { println("缓冲接收: $it") }

    // produce 构建器
    val squares = produce {
        for (i in 1..5) send(i * i)
    }
    squares.consumeEach { println("平方: $it") }

    // 扇出：多个消费者
    val producer = produce {
        for (i in 1..10) send(i)
    }
    repeat(3) { consumerId ->
        launch {
            producer.consumeEach {
                println("消费者$consumerId 处理: $it")
            }
        }
    }
    delay(500)
}

// ===== Flow 流 =====
fun flowDemo() = runBlocking {
    // 构建流
    fun numbers(): Flow<Int> = flow {
        for (i in 1..5) {
            delay(100)
            emit(i) // 发射值
        }
    }

    // 收集流
    numbers().collect { value ->
        println("收到: $value")
    }

    // 流操作符
    numbers()
        .filter { it % 2 == 0 }
        .map { it * it }
        .collect { println("过滤映射: $it") }

    // flowOn 切换上下文
    numbers()
        .flowOn(Dispatchers.Default) // 上游在 Default
        .collect { println("收集: $it") } // 下游在当前上下文

    // 背压处理
    fun fastFlow() = flow {
        for (i in 1..10) {
            delay(50)
            emit(i)
        }
    }

    // buffer：缓冲，生产者消费者并行
    fastFlow()
        .buffer()
        .collect {
            delay(100)
            println("buffer 收集: $it")
        }

    // conflate：只保留最新值，跳过中间值
    fastFlow()
        .conflate()
        .collect {
            delay(100)
            println("conflate 收集: $it")
        }

    // collectLatest：新值到来时取消当前处理
    fastFlow()
        .collectLatest {
            delay(100)
            println("collectLatest: $it")
        }

    // 转换操作符
    numbers()
        .transform { value ->
            emit("开始 $value")
            emit("结束 $value")
        }
        .collect { println(it) }

    // 限长/跳过
    numbers()
        .take(3)
        .collect { println("take: $it") }

    // 聚合
    val sum = numbers().reduce { acc, value -> acc + value }
    println("流求和: $sum")

    // toList
    val list = numbers().toList()
    println("流转列表: $list")

    // StateFlow（热流，有当前状态）
    val state = MutableStateFlow(0)
    launch {
        state.collect { println("StateFlow: $it") }
    }
    state.value = 1
    state.value = 2
    state.value = 3

    // SharedFlow（热流，多订阅者）
    val shared = MutableSharedFlow<Int>(replay = 1)
    launch { shared.collect { println("订阅者1: $it") } }
    launch { shared.collect { println("订阅者2: $it") } }
    delay(100)
    shared.emit(10)
    shared.emit(20)
}

// ===== 组合挂起函数 =====
suspend fun doWork1(): Int {
    delay(100)
    return 10
}

suspend fun doWork2(): Int {
    delay(200)
    return 20
}

fun compositionDemo() = runBlocking {
    // 顺序执行（300ms）
    val time1 = measureTimeMillis {
        val a = doWork1()
        val b = doWork2()
        println("顺序: ${a + b}")
    }
    println("顺序耗时: ${time1}ms")

    // 并行执行（200ms）
    val time2 = measureTimeMillis {
        coroutineScope {
            val a = async { doWork1() }
            val b = async { doWork2() }
            println("并行: ${a.await() + b.await()}")
        }
    }
    println("并行耗时: ${time2}ms")

    // 惰性 async（start = LAZY）
    val lazyA = async(start = CoroutineStart.LAZY) { doWork1() }
    val lazyB = async(start = CoroutineStart.LAZY) { doWork2() }
    lazyA.start() // 手动启动
    lazyB.start()
    println("惰性: ${lazyA.await() + lazyB.await()}")
}

// 运行所有演示
println("=== 基本协程 ===")
basicCoroutine()
println("=== 挂起函数 ===")
suspendDemo()
println("=== async/await ===")
asyncAwaitDemo()
println("=== 调度器 ===")
dispatcherDemo()
println("=== 取消与超时 ===")
cancellationDemo()
println("=== 异常处理 ===")
exceptionDemo()
println("=== Channel ===")
channelDemo()
println("=== Flow ===")
flowDemo()
println("=== 组合 ===")
compositionDemo()

println("协程演示完成")""",
                "tips": "协程是轻量级线程，一个线程可运行成千上万个协程；suspend 函数只能在协程或其他 suspend 函数中调用；runBlocking 阻塞当前线程，用于测试和 main 函数，生产环境不要用；GlobalScope 生命周期不受控，不推荐使用，用自定义 CoroutineScope；Dispatchers.Default 适合 CPU 密集型，Dispatchers.IO 适合网络/文件，Dispatchers.Main 用于 UI 更新；withContext 切换调度器并返回结果，比 launch+join 简洁；async 返回 Deferred<T>，await 获取结果；async 中的异常在 await 时抛出，launch 中的异常直接抛出（需要异常处理器）；coroutineScope 子协程失败会取消所有兄弟协程，supervisorScope 不会；取消是协作式的，CPU 密集型循环需要 ensureActive()/yield() 检查取消状态；delay 是可取消的，Thread.sleep 不是（会阻塞线程）；Channel 是热的，Flow 是冷的（collect 才开始发射）；Flow 操作符（map/filter 等）是惰性的，不修改上游；flowOn 只影响上游，不影响下游；StateFlow 有当前值（value 属性），适合状态管理；SharedFlow 适合事件广播，replay 控制新订阅者收到多少历史值；collectLatest 在新值到来时取消当前处理，适合 UI 更新；withTimeout 超时抛异常，withTimeoutOrNull 返回 null；结构化并发：子协程在父作用域内，父取消子也取消，父等待所有子完成；避免在协程中用 Thread.sleep（阻塞线程），用 delay（挂起协程）。",
            },
            {
                "name": "kotlinx.serialization — JSON 序列化",
                "desc": "kotlinx.serialization 是 Kotlin 官方跨平台序列化框架，支持 JSON/protobuf/CBOR 等格式，通过 @Serializable 注解和编译器插件生成编解码代码，支持多平台（KMP）、默认值、多态、自定义序列化器。",
                "functions": [
                    "@Serializable — 标记可序列化类",
                    "Json.encodeToString(obj) — 序列化为 JSON 字符串",
                    "Json.decodeFromString<T>(json) — 从 JSON 反序列化",
                    "Json.encodeToStream(obj, output) — 序列化到 OutputStream",
                    "Json.decodeFromStream<T>(input) — 从 InputStream 反序列化",
                    "Json { } — 配置 Json 实例",
                    "prettyPrint — 格式化输出",
                    "ignoreUnknownKeys — 忽略未知字段",
                    "isLenient — 宽松解析",
                    "encodeDefaults — 编码默认值",
                    "explicitNulls — 显式编码 null",
                    "coerceInputValues — 强制输入值（枚举默认值）",
                    "useAlternativeNames — 允许多个名称",
                    "@SerialName(\"name\") — 指定序列化名称",
                    "@Transient — 标记不序列化字段（必须有默认值）",
                    "@Required — 必填字段",
                    "@EncodeDefault — 编码默认值",
                    "default 值 — 字段默认值（反序列化时缺失用默认）",
                    "KSerializer<T> — 自定义序列化器接口",
                    "KSerializer.serialize(encoder, value) / deserialize(decoder)",
                    "ContextualSerializer — 上下文序列化器",
                    "PolymorphicSerializer — 多态序列化",
                    "@Polymorphic — 多态标记",
                    "Sealed class — 密封类多态序列化",
                    "JsonElement — JSON DOM 元素",
                    "JsonObject / JsonArray / JsonPrimitive / JsonNull",
                    "Json.parseToJsonElement(json) — 解析为 DOM",
                    "jsonObject / jsonArray — DSL 构建 JSON",
                    "JsonConfiguration — 配置（旧版）",
                    "ProtoBuf / Cbor / Properties — 其他格式",
                    "serializer<T>() — 获取类型的序列化器",
                    "DescriptorSchemaOptions — 描述符选项",
                ],
                "example": """import kotlinx.serialization.*
import kotlinx.serialization.json.*
import kotlinx.serialization.descriptors.*
import kotlinx.serialization.encoding.*
import java.io.ByteArrayInputStream
import java.io.ByteArrayOutputStream

// ===== 基本序列化 =====
@Serializable
data class User(
    val id: Int,
    val name: String,
    val email: String,
    val age: Int? = null, // 可选字段
    val isActive: Boolean = true, // 有默认值
    val tags: List<String> = emptyList()
)

fun basicDemo() {
    val user = User(
        id = 1,
        name = "Alice",
        email = "alice@example.com",
        age = 25,
        isActive = true,
        tags = listOf("admin", "editor")
    )

    // 序列化
    val json = Json.encodeToString(user)
    println("序列化: $json")

    // 反序列化
    val decoded = Json.decodeFromString<User>(json)
    println("反序列化: ${decoded.name}, ${decoded.age}岁")
}

// ===== 格式化配置 =====
fun configDemo() {
    val json = Json {
        prettyPrint = true          // 格式化输出
        ignoreUnknownKeys = true    // 忽略未知字段
        encodeDefaults = true       // 编码默认值
        explicitNulls = false       // 不编码 null
        isLenient = true            // 宽松解析（允许未加引号的键）
        coerceInputValues = true    // 强制输入值（枚举用默认值）
    }

    val user = User(id = 2, name = "Bob", email = "bob@example.com")
    val prettyJson = json.encodeToString(user)
    println("格式化:\\n$prettyJson")

    // 忽略未知字段
    val jsonWithExtra = \"\"\"{"id":3,"name":"Charlie","email":"c@example.com","extra":"ignored"}\"\"\"
    val decoded = json.decodeFromString<User>(jsonWithExtra)
    println("忽略未知字段: ${decoded.name}")
}

// ===== @SerialName 和 @Transient =====
@Serializable
data class Person(
    @SerialName("first_name") val firstName: String,
    @SerialName("last_name") val lastName: String,
    @Transient val internalId: String = "N/A", // 不序列化，必须有默认值
    val age: Int
)

fun serialNameDemo() {
    val person = Person(firstName = "Alice", lastName = "Smith", internalId = "xyz", age = 25)
    val json = Json.encodeToString(person)
    println("SerialName: $json")
    // {"first_name":"Alice","last_name":"Smith","age":25}

    val decoded = Json.decodeFromString<Person>(json)
    println("解码: ${decoded.firstName} ${decoded.lastName}, internalId=${decoded.internalId}")
}

// ===== 嵌套模型 =====
@Serializable
data class Address(
    val street: String,
    val city: String,
    val zipCode: String
)

@Serializable
data class Company(
    val name: String,
    val address: Address,
    val employees: List<Employee>
)

@Serializable
data class Employee(
    val id: Int,
    val name: String,
    val department: String
)

fun nestedDemo() {
    val company = Company(
        name = "Acme Inc",
        address = Address("123 Main St", "Beijing", "100000"),
        employees = listOf(
            Employee(1, "Alice", "Engineering"),
            Employee(2, "Bob", "Marketing")
        )
    )

    val json = Json { prettyPrint = true }.encodeToString(company)
    println("嵌套模型:\\n$json")

    val decoded = Json.decodeFromString<Company>(json)
    println("公司: ${decoded.name}, 员工数: ${decoded.employees.size}")
}

// ===== 集合与字典 =====
fun collectionsDemo() {
    // 列表
    val numbers = listOf(1, 2, 3, 4, 5)
    val json = Json.encodeToString(numbers)
    println("列表: $json")
    val decoded = Json.decodeFromString<List<Int>>(json)
    println("解码列表: $decoded")

    // 字典
    val dict = mapOf("apple" to 5, "banana" to 3, "orange" to 8)
    val dictJson = Json.encodeToString(dict)
    println("字典: $dictJson")
    val decodedDict = Json.decodeFromString<Map<String, Int>>(dictJson)
    println("解码字典: $decodedDict")

    // 嵌套集合
    val nested = mapOf(
        "fruits" to listOf("apple", "banana"),
        "veggies" to listOf("carrot", "broccoli")
    )
    val nestedJson = Json.encodeToString(nested)
    println("嵌套集合: $nestedJson")
}

// ===== 枚举 =====
@Serializable
enum class Direction {
    @SerialName("N") NORTH,
    @SerialName("S") SOUTH,
    @SerialName("E") EAST,
    @SerialName("W") WEST
}

@Serializable
data class Location(val name: String, val direction: Direction)

fun enumDemo() {
    val loc = Location("起点", Direction.NORTH)
    val json = Json.encodeToString(loc)
    println("枚举: $json") // {"name":"起点","direction":"N"}

    val decoded = Json.decodeFromString<Location>(json)
    println("解码枚举: ${decoded.direction}")

    // coerceInputValues：无效枚举用默认值
    val invalidJson = \"\"\"{"name":"测试","direction":"X"}\"\"\"
    val coerced = Json { coerceInputValues = true }.decodeFromString<Location>(invalidJson)
    println("强制默认值: ${coerced.direction}") // NORTH（第一个枚举值）
}

// ===== 多态序列化（密封类）=====
@Serializable
sealed class Shape {
    abstract val area: Double
}

@Serializable
@SerialName("circle")
data class Circle(val radius: Double) : Shape() {
    override val area get() = Math.PI * radius * radius
}

@Serializable
@SerialName("rectangle")
data class Rectangle(val width: Double, val height: Double) : Shape() {
    override val area get() = width * height
}

fun polymorphicDemo() {
    val shapes: List<Shape> = listOf(
        Circle(5.0),
        Rectangle(3.0, 4.0)
    )

    val json = Json { prettyPrint = true }.encodeToString(shapes)
    println("多态:\\n$json")
    // [{"type":"circle","radius":5.0},{"type":"rectangle","width":3.0,"height":4.0}]

    val decoded = Json.decodeFromString<List<Shape>>(json)
    decoded.forEach { shape ->
        when (shape) {
            is Circle -> println("圆形，半径=${shape.radius}, 面积=${shape.area}")
            is Rectangle -> println("矩形，面积=${shape.area}")
        }
    }
}

// ===== 自定义序列化器 =====
@Serializable(with = DateSerializer::class)
data class CustomDate(val year: Int, val month: Int, val day: Int)

object DateSerializer : KSerializer<CustomDate> {
    override val descriptor = PrimitiveSerialDescriptor("CustomDate", PrimitiveKind.STRING)

    override fun serialize(encoder: Encoder, value: CustomDate) {
        encoder.encodeString("%04d-%02d-%02d".format(value.year, value.month, value.day))
    }

    override fun deserialize(decoder: Decoder): CustomDate {
        val string = decoder.decodeString()
        val parts = string.split("-")
        return CustomDate(parts[0].toInt(), parts[1].toInt(), parts[2].toInt())
    }
}

fun customSerializerDemo() {
    val date = CustomDate(2024, 3, 15)
    val json = Json.encodeToString(date)
    println("自定义序列化: $json") // "2024-03-15"

    val decoded = Json.decodeFromString<CustomDate>(json)
    println("解码: ${decoded.year}-${decoded.month}-${decoded.day}")
}

// ===== JSON DOM（JsonElement）=====
fun jsonDomDemo() {
    // 解析为 DOM
    val jsonString = \"\"\"{"name":"Alice","age":25,"scores":[95,87,92],"active":true}\"\"\"
    val element = Json.parseToJsonElement(jsonString)

    // 访问
    val obj = element.jsonObject
    println("name: ${obj["name"]?.jsonPrimitive?.content}")
    println("age: ${obj["age"]?.jsonPrimitive?.int}")
    println("active: ${obj["active"]?.jsonPrimitive?.boolean}")

    val scores = obj["scores"]?.jsonArray
    scores?.forEach { println("分数: ${it.jsonPrimitive.int}") }

    // DSL 构建 JSON
    val built = buildJsonObject {
        put("name", "Bob")
        put("age", 30)
        putJsonArray("skills") {
            add("Kotlin")
            add("Java")
            add("Swift")
        }
        putJsonObject("address") {
            put("city", "Beijing")
            put("country", "China")
        }
    }
    println("DSL 构建: ${Json { prettyPrint = true }.encodeToString(built)}")

    // 修改 DOM
    val mutable = obj.toMutableMap()
    mutable["age"] = JsonPrimitive(26)
    mutable["email"] = JsonPrimitive("alice@example.com")
    val modified = JsonObject(mutable)
    println("修改后: ${Json.encodeToString(modified)}")
}

// ===== 流式序列化 =====
fun streamDemo() {
    val user = User(id = 1, name = "Alice", email = "a@example.com")

    // 序列化到 OutputStream
    val output = ByteArrayOutputStream()
    Json.encodeToStream(user, output)
    println("流式序列化: ${output.toString()}")

    // 从 InputStream 反序列化
    val input = ByteArrayInputStream(output.toByteArray())
    val decoded = Json.decodeFromStream<User>(input)
    println("流式反序列化: ${decoded.name}")
}

// ===== 默认值与必填 =====
@Serializable
data class Config(
    val host: String = "localhost",
    val port: Int = 8080,
    val debug: Boolean = false,
    @Required val appName: String // 必填，没有默认值
)

fun defaultsDemo() {
    // 只提供必填字段
    val json = \"\"\"{"appName":"MyApp"}\"\"\"
    val config = Json.decodeFromString<Config>(json)
    println("默认值: host=${config.host}, port=${config.port}, debug=${config.debug}")

    // 提供所有字段
    val fullJson = \"\"\"{"appName":"App","host":"0.0.0.0","port":9090,"debug":true}\"\"\"
    val fullConfig = Json.decodeFromString<Config>(fullJson)
    println("完整: ${fullConfig.host}:${fullConfig.port}")
}

// 运行所有演示
println("=== 基本序列化 ===")
basicDemo()
println("=== 格式化配置 ===")
configDemo()
println("=== SerialName ===")
serialNameDemo()
println("=== 嵌套模型 ===")
nestedDemo()
println("=== 集合 ===")
collectionsDemo()
println("=== 枚举 ===")
enumDemo()
println("=== 多态 ===")
polymorphicDemo()
println("=== 自定义序列化器 ===")
customSerializerDemo()
println("=== JSON DOM ===")
jsonDomDemo()
println("=== 流式 ===")
streamDemo()
println("=== 默认值 ===")
defaultsDemo()

println("序列化演示完成")""",
                "tips": "kotlinx.serialization 需要在 build.gradle 中配置插件和依赖（org.jetbrains.kotlin.plugin.serialization + kotlinx-serialization-json）；@Serializable 注解的数据类自动生成序列化器，不需要手动写；字段有默认值时反序列化缺失会用默认值，没有默认值且缺失会抛异常；@Transient 标记的字段不参与序列化，必须有默认值；@SerialName 指定 JSON 中的字段名，支持 snake_case 等；Json 配置用 Json { } DSL，prettyPrint/ignoreUnknownKeys 等；ignoreUnknownKeys=true 是实际开发中常用的（API 返回额外字段不报错）；encodeDefaults=false 时默认值字段不编码（减少体积）；多态序列化用密封类（sealed class）+ @SerialName，自动添加 type 字段；自定义序列化器实现 KSerializer<T>，descriptor 定义结构，serialize/deserialize 实现逻辑；JsonElement DOM 适合动态 JSON（结构不确定），jsonObject/jsonArray DSL 构建；流式序列化 encodeToStream/decodeFromStream 适合大文件；coerceInputValues=true 时无效枚举值用第一个枚举值（不抛异常）；explicitNulls=false 时 null 值字段不编码；kotlinx.serialization 是跨平台的（KMP），支持 JS/Native；性能优于 Gson/Jackson（编译期生成代码，无反射）；@Required 标记必填字段（即使有默认值也必须提供）；Contextual 用于运行时决定序列化器（如 java.util.Date）；JsonNames 注解（Kotlin 1.7+）允许一个字段有多个 JSON 名称。",
            },
            {
                "name": "kotlin.sequences / sequences — 序列与集合操作",
                "desc": "Kotlin Sequence 是惰性求值的集合类型，类似 Java Stream，支持链式操作但不创建中间集合，适合大数据量和复杂管道操作，与集合操作符一致但执行策略不同。",
                "functions": [
                    "sequenceOf(...) — 创建序列",
                    "list.asSequence() — 集合转序列",
                    "generateSequence(seed) { next } — 生成无限序列",
                    "sequence { yield(x); yieldAll(list) } — 构建器",
                    "seq.map { } / mapIndexed / mapNotNull",
                    "seq.filter { } / filterNot / filterNotNull / filterIsInstance",
                    "seq.fold(initial) { } / reduce { } / foldIndexed",
                    "seq.groupBy { } / groupingBy { } / eachCount",
                    "seq.sorted() / sortedBy { } / sortedDescending",
                    "seq.distinct() / distinctBy { }",
                    "seq.flatMap { } / flatten",
                    "seq.chunked(n) / windowed(size, step)",
                    "seq.partition { }",
                    "seq.any { } / all { } / none { } / count { }",
                    "seq.sum() / average() / max() / min() / maxBy { }",
                    "seq.associate { } / associateBy { } / associateWith { }",
                    "seq.forEach { } / forEachIndexed { }",
                    "seq.take(n) / takeLast(n) / takeWhile { } / drop(n)",
                    "seq.first() / last() / firstOrNull / find { }",
                    "seq.contains(x) / indexOf(x) / indexOfFirst { }",
                    "seq.toList() / toSet() / toMap() / toTypedArray()",
                    "seq.toMutableList() / toHashSet()",
                    "seq.joinToString(separator) — 连接为字符串",
                    "seq.zip(other) / unzip()",
                    "seq.plus(x) / minus(x)",
                    "seq.onEach { } — 查看元素（不修改）",
                    "seq.withIndex() — 带索引",
                    "seq.constrainOnce() — 只遍历一次",
                    "seq.dropWhile { } / takeWhile { }",
                    "seq.sortedWith(comparator)",
                    "seq.reduceOrNull / foldRight",
                    "seq.runningFold(initial) { } — 累积中间结果",
                    "seq.scan(initial) { } — 别名 runningFold",
                    "infinite sequence — 无限序列（take 限制）",
                    "seq.shuffled() — 打乱",
                    "seq.reversed() — 反转",
                ],
                "example": """// ===== 创建序列 =====
// 从元素创建
val seq1 = sequenceOf(1, 2, 3, 4, 5)

// 从集合转换
val list = listOf(1, 2, 3, 4, 5, 6, 7, 8, 9, 10)
val seq2 = list.asSequence()

// generateSequence 生成无限序列
val naturalNumbers = generateSequence(1) { it + 1 } // 1,2,3,...
val powersOf2 = generateSequence(1) { it * 2 } // 1,2,4,8,16,...

// sequence 构建器
val seq3 = sequence {
    yield(1)
    yieldAll(listOf(2, 3))
    yield(4)
    yieldAll(generateSequence(5) { it + 1 }.take(3))
} // [1,2,3,4,5,6,7]

// 空序列
val emptySeq = emptySequence<Int>()

// ===== 惰性求值演示 =====
println("=== 惰性求值 ===")
val eagerResult = list
    .filter { it % 2 == 0 } // 创建中间列表
    .map { it * it }          // 创建中间列表
    .take(3)                   // 创建中间列表
println("集合（急切）: $eagerResult")

val lazyResult = list.asSequence()
    .filter { it % 2 == 0 } // 不执行
    .map { it * it }          // 不执行
    .take(3)                   // 不执行
    .toList()                  // 终端操作才执行
println("序列（惰性）: $lazyResult")

// 验证惰性：加打印
println("\\n=== 执行顺序 ===")
list.asSequence()
    .filter {
        println("filter $it")
        it % 2 == 0
    }
    .map {
        println("map $it")
        it * it
    }
    .take(2)
    .toList()
// 输出：filter 1, filter 2, map 2, filter 3, filter 4, map 4
// 每个元素走完整个管道，而不是先全部 filter 再全部 map

// ===== 常用操作 =====
println("\\n=== 常用操作 ===")

// map / filter
val doubled = seq2.map { it * 2 }.toList()
val evens = seq2.filter { it % 2 == 0 }.toList()

// fold / reduce
val sum = seq2.fold(0) { acc, i -> acc + i }
val product = seq2.reduce { acc, i -> acc * i }
println("sum=$sum, product=$product")

// runningFold（累积中间结果）
val cumulative = seq2.take(5).runningFold(0) { acc, i -> acc + i }.toList()
println("累积: $cumulative") // [0,1,3,6,10,15]

// groupBy
val words = sequenceOf("apple", "banana", "cherry", "avocado", "blueberry")
val byFirstLetter = words.groupBy { it.first() }
println("按首字母分组: $byFirstLetter")

// 分组统计
val freq = words.groupingBy { it.first() }.eachCount()
println("频次: $freq")

// sorted
val sortedAsc = seq2.sorted().toList()
val sortedDesc = seq2.sortedDescending().toList()
val sortedByLength = words.sortedBy { it.length }.toList()
println("按长度排序: $sortedByLength")

// distinct
val withDup = sequenceOf(1, 2, 2, 3, 3, 3, 4)
val unique = withDup.distinct().toList()
println("去重: $unique")

// flatMap
val nested = sequenceOf(listOf(1, 2), listOf(3, 4), listOf(5, 6))
val flattened = nested.flatten().toList()
val flatMapped = nested.flatMap { it.asSequence().map { x -> x * 10 } }.toList()
println("flatten=$flattened, flatMap=$flatMapped")

// chunked / windowed
val chunks = seq2.chunked(3).toList()
val windows = seq2.take(5).windowed(3).toList()
println("chunks=$chunks")
println("windows=$windows")

// partition
val (evenList, oddList) = seq2.partition { it % 2 == 0 }
println("偶数=$evenList, 奇数=$oddList")

// 布尔判断
val anyGreater = seq2.any { it > 10 }
val allPositive = seq2.all { it > 0 }
val noneZero = seq2.none { it == 0 }
val countGreater5 = seq2.count { it > 5 }
println("any>10=$anyGreater, all>0=$allPositive, none=0=$noneZero, count>5=$countGreater5")

// 聚合
val total = seq2.sum()
val avg = seq2.average()
val maxVal = seq2.maxOrNull()
val minVal = seq2.minOrNull()
val maxByLength = words.maxByOrNull { it.length }
println("sum=$total, avg=$avg, max=$maxVal, min=$minVal")

// associate
val lengthMap = words.associateWith { it.length }.toMap()
println("长度映射: $lengthMap")

// take / drop
val first3 = seq2.take(3).toList()
val last3 = seq2.takeLast(3).toList()
val whileLess5 = seq2.takeWhile { it < 5 }.toList()
val drop3 = seq2.drop(3).toList()
val dropWhile = seq2.dropWhile { it < 5 }.toList()
println("take3=$first3, takeWhile<5=$whileLess5, drop3=$drop3")

// first / find
val first = seq2.first()
val firstEven = seq2.first { it % 2 == 0 }
val firstOrNull = seq2.firstOrNull { it > 100 } // null
val found = seq2.find { it > 5 }
println("first=$first, firstEven=$firstEven, firstOrNull>100=$firstOrNull")

// joinToString
val joined = seq2.take(5).joinToString(separator = ", ", prefix = "[", postfix = "]")
println("join: $joined")

// zip
val zipped = seq2.take(5).zip(sequenceOf("a", "b", "c", "d", "e")).toList()
println("zip: $zipped")

// onEach（调试）
val result = seq2.take(3)
    .onEach { println("处理: $it") }
    .map { it * 10 }
    .toList()
println("onEach 结果: $result")

// ===== 无限序列 =====
println("\\n=== 无限序列 ===")

// 斐波那契数列
val fibonacci = generateSequence(Pair(0, 1)) { Pair(it.second, it.first + it.second) }
    .map { it.first }
    .take(10)
    .toList()
println("斐波那契: $fibonacci") // [0,1,1,2,3,5,8,13,21,34]

// 素数序列
fun isPrime(n: Int) = n > 1 && (2 until n).none { n % it == 0 }
val primes = generateSequence(2) { it + 1 }
    .filter { isPrime(it) }
    .take(10)
    .toList()
println("素数: $primes") // [2,3,5,7,11,13,17,19,23,29]

// 随机数
val randoms = generateSequence { kotlin.random.Random.nextInt(1, 100) }
    .take(5)
    .toList()
println("随机数: $randoms")

// ===== 性能对比 =====
println("\\n=== 性能对比 ===")
val bigList = (1..1_000_000).toList()

// 集合（急切）：创建多个中间列表，内存占用大
val eagerTime = measureTimeMillis {
    bigList
        .filter { it % 2 == 0 }
        .map { it * it }
        .take(100)
        .toList()
}
println("集合耗时: ${eagerTime}ms")

// 序列（惰性）：不创建中间集合，内存占用小
val lazyTime = measureTimeMillis {
    bigList.asSequence()
        .filter { it % 2 == 0 }
        .map { it * it }
        .take(100)
        .toList()
}
println("序列耗时: ${lazyTime}ms")

// ===== 序列 vs 集合选择 =====
// 用序列的场景：
// 1. 大数据量（避免中间集合内存）
// 2. 复杂管道（多个 map/filter 链式）
// 3. 无限序列
// 4. 只需要部分结果（take 限制）
// 5. 延迟计算（需要时才计算）

// 用集合的场景：
// 1. 小数据量（序列有开销）
// 2. 需要多次遍历（序列默认只能遍历一次）
// 3. 需要随机访问（序列不支持索引）
// 4. 简单操作（单个 map/filter）

// ===== 多次遍历问题 =====
val seq = sequenceOf(1, 2, 3)
seq.forEach { print("$it ") } // 第一次
println()
// seq.forEach { } // 第二次可能抛异常（取决于序列类型）
// 解决：转集合 toList() 后多次遍历
val materialized = seq.toList()
materialized.forEach { print("$it ") }
materialized.forEach { print("$it ") }
println()

// constrainOnce：确保只遍历一次
val constrained = sequenceOf(1, 2, 3).constrainOnce()
constrained.toList() // 第一次 OK
// constrained.toList() // 第二次抛 IllegalStateException

println("\\n序列操作演示完成")""",
                "tips": "Sequence 是惰性求值的，中间操作（map/filter 等）不立即执行，直到终端操作（toList/first/count 等）才触发；Sequence 不创建中间集合，大数据量和复杂管道时内存效率高；小数据量用 List 更简单（Sequence 有函数调用开销）；Sequence 默认只能遍历一次，多次遍历先 toList() 物化；generateSequence 创建无限序列，必须用 take/limit 限制否则终端操作会无限循环；sequence { } 构建器用 yield/yieldAll 发射元素，支持挂起函数（suspend）；onEach 用于调试查看元素，不修改元素；runningFold/scan 返回所有中间累积结果（包括初始值）；fold 有初始值，reduce 没有（空序列抛异常）；groupBy 返回 Map，groupingBy + eachCount 用于统计频次；sorted/sortedBy 是有状态操作（需要收集所有元素才能排序），之后的操作不再惰性；distinct 也是有状态操作；take/takeWhile 是短路操作（找到足够元素后停止处理后续）；chunked/windowed 是有状态操作；associate/associateBy 构建 Map，key 重复会覆盖；partition 返回 Pair，解构赋值；Sequence 不支持索引访问（[]），需要随机访问转 List；性能：大数据量+复杂管道用 Sequence，小数据量+简单操作用 List；Sequence 的 map/filter 签名与 List 一致，迁移简单；asSequence() 不复制，只是包装；Sequence 可以并行？不能，Kotlin 没有并行流（Java 的 parallelStream），需要并行用协程；measureTimeMillis 是 kotlin.system 包的函数。",
            },
        ],
    }

_more7 = _more_modules7()
for _k, _v in _more7.items():
    if _k not in LANG_MODULES:
        LANG_MODULES[_k] = _v
del _more7, _more_modules7



# ============================================================
# 三、K12 知识点详情生成：语数英每个知识点完整教学内容
# ============================================================

# 数学知识点详细模板
# ============================================================
# 数学知识点类别详情库
# ============================================================
_MATH_CATEGORY = {
    "数的认识": {
        "definition": "数的认识是数学学习的基础，包括整数、小数、分数、百分数、负数等各类数的概念、意义、读写方法和大小比较。",
        "key_points": [
            "整数：包括正整数、零、负整数，数位顺序表从右往左依次是个位、十位、百位、千位、万位、十万位、百万位、千万位、亿位",
            "小数：由整数部分、小数点和小数部分组成，小数部分从左往右依次是十分位、百分位、千分位",
            "分数：把单位'1'平均分成若干份，表示这样的一份或几份的数，分子在上分母在下",
            "百分数：表示一个数是另一个数的百分之几的数，也叫百分率或百分比，通常用%表示",
            "负数：比0小的数，用负号'-'标记，如-1、-2.5、-1/2",
            "数的分类：实数分为有理数和无理数，有理数分为整数和分数，整数分为正整数、零、负整数",
        ],
        "formulas": [
            "数位顺序：个级（个十百千）、万级（万十万百万千万）、亿级（亿十亿百亿千亿）",
            "小数性质：小数末尾添上0或去掉0，小数大小不变",
            "分数基本性质：分子分母同时乘或除以同一个不为0的数，分数大小不变",
            "分数与除法关系：a ÷ b = a/b (b≠0)",
            "百分数与小数互化：百分数化小数去掉%小数点左移两位；小数化百分数小数点右移两位加%",
        ],
        "examples": [
            "例1：3050000 读作三百零五万，改写成用万作单位是305万",
            "例2：0.35 = 35/100 = 7/20 = 35%",
            "例3：比较大小：-3 < -1 < 0 < 0.5 < 1/2 < 1 < 2",
            "例4：一个数由5个十、3个十分之一和7个百分之一组成，这个数是50.37",
        ],
        "methods": "数的认识学习法：1.理解各类数的意义和概念；2.掌握数位顺序表和计数单位；3.熟练进行数的读写和改写；4.掌握数的大小比较方法；5.在实际问题中运用数的概念。建议多做数的读写、改写、比较练习，打好数学基础。",
        "common_mistakes": ["数位和计数单位混淆（数位是位置，计数单位是个十百千）", "小数位数判断错误（0.35是两位小数不是一位）", "分数通分约分错误（没有找最小公倍数或最大公因数）", "负数大小比较错误（-3 > -1是错的，负数绝对值大的反而小）", "百分数与小数互化时小数点移动方向错误"],
    },
    "四则运算": {
        "definition": "四则运算是指加法、减法、乘法、除法四种基本运算，是数学计算的基础。掌握四则运算的意义、法则、顺序和简便运算方法至关重要。",
        "key_points": [
            "加法：把两个数合并成一个数的运算，a + b = c，交换律a+b=b+a，结合律(a+b)+c=a+(b+c)",
            "减法：已知两个加数的和与其中一个加数，求另一个加数的运算，a - b = c，减法是加法的逆运算",
            "乘法：求几个相同加数和的简便运算，a × b = c，交换律a×b=b×a，结合律(a×b)×c=a×(b×c)，分配律(a+b)×c=a×c+b×c",
            "除法：已知两个因数的积与其中一个因数，求另一个因数的运算，a ÷ b = c (b≠0)，除法是乘法的逆运算",
            "运算顺序：先乘除后加减，有括号先算括号内（先小括号再中括号最后大括号），同级运算从左到右",
            "简便运算：运用运算定律（交换律、结合律、分配律）和运算性质进行简便计算",
        ],
        "formulas": [
            "加法交换律：a + b = b + a",
            "加法结合律：(a + b) + c = a + (b + c)",
            "乘法交换律：a × b = b × a",
            "乘法结合律：(a × b) × c = a × (b × c)",
            "乘法分配律：(a + b) × c = a × c + b × c",
            "减法性质：a - b - c = a - (b + c)；a - (b - c) = a - b + c",
            "除法性质：a ÷ b ÷ c = a ÷ (b × c)；a ÷ (b ÷ c) = a ÷ b × c",
        ],
        "examples": [
            "例1：25 × 32 × 125 = 25 × 4 × 8 × 125 = (25×4) × (8×125) = 100 × 1000 = 100000（乘法结合律简便运算）",
            "例2：99 × 38 + 38 = 38 × (99 + 1) = 38 × 100 = 3800（乘法分配律简便运算）",
            "例3：567 - 128 - 72 = 567 - (128 + 72) = 567 - 200 = 367（减法性质）",
            "例4：3600 ÷ 25 ÷ 4 = 3600 ÷ (25 × 4) = 3600 ÷ 100 = 36（除法性质）",
            "例5：混合运算：(80 - 14) ÷ 6 × 3 = 66 ÷ 6 × 3 = 11 × 3 = 33（先括号，再从左到右）",
        ],
        "methods": "四则运算学习法：1.理解四则运算的意义和相互关系（加减互逆、乘除互逆）；2.熟练掌握运算法则和运算顺序；3.牢记运算定律和运算性质；4.多做简便运算练习，提高计算速度和准确率；5.养成验算习惯。计算时要认真审题，看清数字和运算符号，选择合适的方法。",
        "common_mistakes": ["运算顺序错误（先加减后乘除，或括号顺序错误）", "简便运算时运算定律用错（分配律和结合律混淆）", "计算粗心（数字抄错、进位退位错误）", "除法中忽略除数不能为0", "减法性质和除法性质去括号时符号错误"],
    },
    "方程": {
        "definition": "方程是含有未知数的等式，解方程是求方程中未知数的值的过程。方程是解决实际问题的重要工具，通过设未知数、列方程、解方程来解决问题。",
        "key_points": [
            "方程的定义：含有未知数的等式叫做方程，方程必须同时满足两个条件：①是等式；②含有未知数",
            "方程的解：使方程左右两边相等的未知数的值叫做方程的解",
            "解方程：求方程的解的过程叫做解方程",
            "等式的性质：①等式两边同时加上或减去同一个数，等式仍成立；②等式两边同时乘或除以同一个不为0的数，等式仍成立",
            "解方程步骤：去分母→去括号→移项→合并同类项→系数化为1",
            "列方程解应用题步骤：①审题，弄清题意；②设未知数（直接设或间接设）；③找等量关系列方程；④解方程；⑤检验并写出答案",
        ],
        "formulas": [
            "等式性质1：若a=b，则a±c=b±c",
            "等式性质2：若a=b，则a×c=b×c；若a=b且c≠0，则a÷c=b÷c",
            "一元一次方程标准形式：ax + b = 0 (a≠0)，解为x = -b/a",
            "移项法则：把方程中的某一项改变符号后，从方程的一边移到另一边",
            "去括号法则：括号前是'+'号，去括号后括号内各项不变号；括号前是'-'号，去括号后括号内各项都变号",
        ],
        "examples": [
            "例1：解方程 3x + 5 = 20。解：3x = 20 - 5（移项），3x = 15（合并），x = 5（系数化为1）。检验：3×5+5=20 ✓",
            "例2：解方程 2(x - 3) = x + 4。解：2x - 6 = x + 4（去括号），2x - x = 4 + 6（移项），x = 10（合并）",
            "例3：列方程解应用题：小明买了3支钢笔和5本笔记本，共花了45元，已知每支钢笔10元，每本笔记本多少元？解：设每本笔记本x元，列方程 3×10 + 5x = 45，30 + 5x = 45，5x = 15，x = 3。答：每本笔记本3元。",
            "例4：解方程 x/2 + x/3 = 5。解：两边乘6去分母 3x + 2x = 30，5x = 30，x = 6",
        ],
        "methods": "方程学习法：1.理解方程的概念和等式的性质；2.掌握解方程的一般步骤和方法；3.熟练进行移项、去括号、合并同类项等操作；4.学会找等量关系列方程解应用题；5.养成检验的习惯。列方程解应用题的关键是找等量关系，要认真审题，找出题目中的等量关系。",
        "common_mistakes": ["方程和等式概念混淆（所有方程都是等式，但等式不一定是方程）", "移项时忘记变号", "去括号时符号错误（括号前是负号时忘记变号）", "去分母时漏乘没有分母的项", "列方程时等量关系找错", "解完方程不检验"],
    },
    "几何图形": {
        "definition": "几何图形是数学的重要组成部分，包括平面图形和立体图形，研究图形的形状、大小、位置关系及其性质。掌握几何图形的特征、周长、面积、体积计算是重点。",
        "key_points": [
            "平面图形：长方形、正方形、三角形、平行四边形、梯形、圆、扇形等，研究周长和面积",
            "立体图形：长方体、正方体、圆柱、圆锥、球等，研究表面积和体积",
            "三角形分类：按角分锐角三角形、直角三角形、钝角三角形；按边分等边三角形、等腰三角形、不等边三角形",
            "三角形性质：三角形内角和180°，任意两边之和大于第三边，任意两边之差小于第三边",
            "圆的性质：圆心决定圆的位置，半径决定圆的大小；同圆或等圆中直径是半径的2倍",
            "图形变换：平移、旋转、轴对称，图形变换后形状大小不变，位置或方向改变",
        ],
        "formulas": [
            "长方形：周长C=(a+b)×2，面积S=a×b",
            "正方形：周长C=4a，面积S=a²",
            "三角形：面积S=ah÷2，内角和180°",
            "平行四边形：面积S=ah",
            "梯形：面积S=(a+b)h÷2",
            "圆：周长C=2πr=πd，面积S=πr²",
            "长方体：表面积S=(ab+ah+bh)×2，体积V=abh",
            "正方体：表面积S=6a²，体积V=a³",
            "圆柱：侧面积=2πrh，表面积=2πr²+2πrh，体积V=πr²h",
            "圆锥：体积V=1/3πr²h",
        ],
        "examples": [
            "例1：一个长方形长8厘米宽5厘米，周长=(8+5)×2=26厘米，面积=8×5=40平方厘米",
            "例2：一个三角形底6厘米高4厘米，面积=6×4÷2=12平方厘米",
            "例3：一个圆半径3厘米，周长=2×3.14×3=18.84厘米，面积=3.14×3²=28.26平方厘米",
            "例4：一个圆柱底面半径2厘米高5厘米，体积=3.14×2²×5=62.8立方厘米",
            "例5：一个圆锥底面半径3厘米高4厘米，体积=1/3×3.14×3²×4=37.68立方厘米",
        ],
        "methods": "几何图形学习法：1.认识各类图形的特征和性质；2.牢记周长、面积、体积公式；3.理解公式的推导过程（不要死记硬背）；4.多做图形计算练习，注意单位统一；5.学会画图形辅助理解。解题时要先弄清图形类型，找出已知条件，选择合适的公式计算。",
        "common_mistakes": ["公式记错（面积和周长公式混淆，圆锥体积忘记乘1/3）", "单位不统一（计算时单位没有换算成同一单位）", "三角形面积忘记除以2", "圆的周长和面积公式混淆（周长是2πr，面积是πr²）", "计算表面积时漏算面（如无盖水桶只有一个底面）"],
    },
    "应用题": {
        "definition": "应用题是用语言文字叙述实际问题，要求运用数学知识解决的题目。应用题类型多样，包括行程问题、工程问题、分数百分数问题、浓度问题、利润问题等，是数学学习的重点和难点。",
        "key_points": [
            "行程问题：路程=速度×时间，相遇问题路程和=速度和×相遇时间，追及问题路程差=速度差×追及时间",
            "工程问题：工作总量=工作效率×工作时间，通常把工作总量看作单位'1'，合作效率=各效率之和",
            "分数应用题：找准单位'1'，求单位'1'用除法，求部分量用乘法，关键是找到对应量和对应分率",
            "百分数应用题：包括求百分率、求一个数比另一个数多（少）百分之几、折扣、利息、纳税等",
            "浓度问题：浓度=溶质质量÷溶液质量×100%，溶液质量=溶质质量+溶剂质量",
            "利润问题：利润=售价-成本，利润率=利润÷成本×100%，售价=成本×(1+利润率)",
        ],
        "formulas": [
            "行程问题：路程=速度×时间；相遇：路程和=速度和×时间；追及：路程差=速度差×时间",
            "工程问题：工作总量=工作效率×工作时间；合作：1÷(1/a+1/b)",
            "分数应用题：单位'1'的量=对应量÷对应分率；部分量=单位'1'的量×对应分率",
            "浓度问题：浓度=溶质÷溶液×100%；混合浓度=总溶质÷总溶液×100%",
            "利润问题：利润=售价-成本；利润率=利润÷成本×100%；售价=成本×(1+利润率)",
            "利息问题：利息=本金×利率×时间；本息和=本金+利息",
        ],
        "examples": [
            "例1（相遇问题）：甲乙两车从相距480千米的两地同时出发相向而行，甲车每小时60千米，乙车每小时40千米，几小时后相遇？解：480÷(60+40)=480÷100=4.8小时",
            "例2（工程问题）：一项工程甲单独做10天完成，乙单独做15天完成，两人合作几天完成？解：1÷(1/10+1/15)=1÷(3/30+2/30)=1÷5/30=6天",
            "例3（分数应用题）：一本书有240页，小明第一天看了全书的1/4，第二天看了全书的1/3，还剩多少页？解：240×(1-1/4-1/3)=240×5/12=100页",
            "例4（百分数应用题）：一件商品原价200元，打八折出售，现价多少元？解：200×80%=160元",
            "例5（浓度问题）：把20克盐放入80克水中，盐水浓度是多少？解：20÷(20+80)×100%=20÷100×100%=20%",
        ],
        "methods": "应用题解题法：1.认真审题，弄清题意（已知什么、求什么）；2.分析数量关系，确定解题思路；3.选择合适的方法（算术法或方程法）；4.列式计算；5.检验并写出答案。对于复杂应用题，可以画线段图、列表格辅助分析。关键是找准数量关系和单位'1'。",
        "common_mistakes": ["审题不仔细，看错数字或条件", "单位'1'找错（分数应用题中谁是单位'1'判断错误）", "行程问题中速度和与速度差用错（相遇用速度和，追及用速度差）", "工程问题中工作效率和工作时间混淆", "百分数应用题中'增加了'和'增加到'混淆", "计算错误或忘记写单位和答语"],
    },
}


_MATH_DETAIL = {
    "整数与数位": {
        "definition": "整数是正整数、零和负整数的统称。数位是指一个数中每个数字所占的位置，从右往左依次是个位、十位、百位、千位、万位等。",
        "key_points": [
            "数位顺序：个位、十位、百位、千位、万位、十万位、百万位、千万位、亿位",
            "计数单位：个（一）、十、百、千、万、十万、百万、千万、亿",
            "每相邻两个计数单位之间的进率都是10（十进制计数法）",
            "读数时从高位读起，每级末尾的0不读，其他数位有一个0或连续几个0都只读一个零",
            "写数时从高位写起，哪一位上一个单位也没有就在那一位上写0",
        ],
        "formulas": ["数位 = 数字 × 计数单位", "例：3456 = 3×1000 + 4×100 + 5×10 + 6×1"],
        "examples": [
            "例1：3456 读作三千四百五十六，其中3在千位表示3个千，4在百位表示4个百",
            "例2：五万零三百 写作50300（万位5，百位3，其他位补0）",
            "例3：一个数由5个千万、3个十万、7个百组成，这个数是50300700",
        ],
        "methods": "读数分级法：从右往左每四位一级，分为个级、万级、亿级；万级和亿级按照个级读法读，再在后面加万或亿字。",
        "common_mistakes": ["读数时漏读万或亿字", "中间有多个0时读成多个零", "写数时漏写0占位", "混淆数位和计数单位"],
    },
    "四则运算": {
        "definition": "四则运算是加法、减法、乘法、除法四种运算的统称。加法和减法是第一级运算，乘法和除法是第二级运算。",
        "key_points": [
            "加法：把两个数合并成一个数的运算，a + b = c",
            "减法：已知两个加数的和与其中一个加数，求另一个加数的运算，c - a = b",
            "乘法：求几个相同加数和的简便运算，a × b = c",
            "除法：已知两个因数的积与其中一个因数，求另一个因数的运算，c ÷ a = b",
            "加减法互为逆运算，乘除法互为逆运算",
            "0加任何数等于原数，0乘任何数等于0，0不能作除数",
        ],
        "formulas": [
            "加数 + 加数 = 和；和 - 一个加数 = 另一个加数",
            "被减数 - 减数 = 差；被减数 - 差 = 减数；差 + 减数 = 被减数",
            "因数 × 因数 = 积；积 ÷ 一个因数 = 另一个因数",
            "被除数 ÷ 除数 = 商……余数；被除数 = 商 × 除数 + 余数",
        ],
        "examples": [
            "例1：25 + 37 = 62（个位5+7=12写2进1，十位2+3+1=6）",
            "例2：83 - 45 = 38（个位3减5不够，向十位借1当10，13-5=8）",
            "例3：24 × 13 = 312（24×3=72，24×10=240，72+240=312）",
            "例4：96 ÷ 4 = 24（9÷4商2余1，16÷4商4）",
        ],
        "methods": "竖式计算法：相同数位对齐，从低位算起；加法满十进一，减法不够减向前一位借一当十；乘法用乘数每一位分别乘被乘数再相加；除法从高位除起。",
        "common_mistakes": ["加法忘记进位", "减法忘记借位", "乘法数位对错", "除法商的位置写错或余数大于除数"],
    },
    "运算定律与简便计算": {
        "definition": "运算定律是加法和乘法运算中普遍适用的规律，利用这些定律可以使计算更加简便。",
        "key_points": [
            "加法交换律：a + b = b + a",
            "加法结合律：(a + b) + c = a + (b + c)",
            "乘法交换律：a × b = b × a",
            "乘法结合律：(a × b) × c = a × (b × c)",
            "乘法分配律：(a + b) × c = a × c + b × c",
            "减法性质：a - b - c = a - (b + c)",
            "除法性质：a ÷ b ÷ c = a ÷ (b × c)",
        ],
        "formulas": [
            "加法交换律：a + b = b + a",
            "加法结合律：(a + b) + c = a + (b + c)",
            "乘法交换律：a × b = b × a",
            "乘法结合律：(a × b) × c = a × (b × c)",
            "乘法分配律：(a + b) × c = a × c + b × c",
            "减法性质：a - b - c = a - (b + c)",
            "除法性质：a ÷ b ÷ c = a ÷ (b × c)",
        ],
        "examples": [
            "例1：25 + 37 + 75 = (25 + 75) + 37 = 137（加法交换律+结合律）",
            "例2：125 × 37 × 8 = (125 × 8) × 37 = 37000（乘法交换律+结合律）",
            "例3：(40 + 4) × 25 = 40 × 25 + 4 × 25 = 1100（乘法分配律）",
            "例4：347 - 125 - 75 = 347 - (125 + 75) = 147（减法性质）",
            "例5：3600 ÷ 25 ÷ 4 = 3600 ÷ (25 × 4) = 36（除法性质）",
        ],
        "methods": "简便计算四步法：一看（看数字特点）、二想（想能用什么定律）、三算（按定律计算）、四查（检查结果）。常见凑整：25×4=100，125×8=1000。",
        "common_mistakes": ["乘法分配律漏乘", "减法性质去括号时符号错误", "除法性质去括号时符号错误", "不能简便的题目强行简便"],
    },
    "行程问题": {
        "definition": "行程问题是研究物体运动的速度、时间和路程三者关系的应用题，是小学数学应用题的重点。",
        "key_points": [
            "基本关系：路程 = 速度 × 时间",
            "速度 = 路程 ÷ 时间",
            "时间 = 路程 ÷ 速度",
            "相遇问题：路程和 = 速度和 × 相遇时间",
            "追及问题：路程差 = 速度差 × 追及时间",
            "相遇时间 = 总路程 ÷ 速度和",
            "追及时间 = 路程差 ÷ 速度差",
        ],
        "formulas": [
            "路程 = 速度 × 时间；速度 = 路程 ÷ 时间；时间 = 路程 ÷ 速度",
            "相遇问题：总路程 = (甲速度 + 乙速度) × 相遇时间",
            "追及问题：路程差 = (快速度 - 慢速度) × 追及时间",
            "环形相遇：第一次相遇路程和 = 一圈长度",
            "环形追及：第一次追上路程差 = 一圈长度",
            "流水行船：顺水速度 = 船速 + 水速；逆水速度 = 船速 - 水速",
        ],
        "examples": [
            "例1：汽车每小时行60千米，4小时行多少千米？60×4=240千米",
            "例2（相遇）：甲乙两车从相距300千米两地同时相向而行，甲60km/h，乙40km/h，几小时相遇？300÷(60+40)=3小时",
            "例3（追及）：甲车在乙车前方50千米，甲40km/h，乙60km/h，乙几小时追上？50÷(60-40)=2.5小时",
            "例4（往返）：小明从家到学校每分钟60米，10分钟到达；回家用15分钟，回家速度？60×10÷15=40米/分",
        ],
        "methods": "行程问题三步法：1.画线段图理清关系；2.判断类型（相遇/追及/基本）；3.套用对应公式。关键分清路程和还是路程差，速度和还是速度差。",
        "common_mistakes": ["相遇误用速度差，追及误用速度和", "单位不统一", "火车过桥忘记加火车长度", "流水行船混淆顺水逆水速度"],
    },
    "鸡兔同笼": {
        "definition": "鸡兔同笼问题是中国古代经典数学问题，已知鸡兔的总头数和总脚数，求鸡和兔各有多少只。",
        "key_points": [
            "鸡有2只脚，兔有4只脚",
            "假设法：假设全是鸡或全是兔，根据脚数差计算",
            "方程法：设鸡有x只，兔有(总头数-x)只，列方程",
            "抬脚法：让所有动物抬起2只脚，剩下的脚都是兔子的",
            "兔的只数 = (总脚数 - 总头数×2) ÷ (4-2)",
            "鸡的只数 = 总头数 - 兔的只数",
        ],
        "formulas": [
            "假设全是鸡：兔 = (总脚数 - 总头数×2) ÷ 2",
            "假设全是兔：鸡 = (总头数×4 - 总脚数) ÷ 2",
            "方程法：2x + 4(总头数-x) = 总脚数",
        ],
        "examples": [
            "例1：鸡兔同笼，35个头，94只脚，各多少只？假设全是鸡：35×2=70，多出94-70=24，兔=24÷2=12只，鸡=35-12=23只",
            "例2：停车场汽车和摩托车共24辆，86个轮子，各多少辆？假设全是摩托：24×2=48，多出86-48=38，汽车=38÷2=19辆，摩托=5辆",
            "例3：100和尚吃100馒头，大和尚1人吃3个，小和尚3人吃1个，各多少人？假设全是大和尚：100×3=300，多出200，小和尚=200÷(8/3)=75人，大和尚=25人",
        ],
        "methods": "假设法最常用：1.假设全是鸡算出假设总脚数；2.与实际比较算出差值；3.差值除以脚数差得到兔的只数；4.总头数减兔得鸡。口诀：设鸡得兔，设兔得鸡。",
        "common_mistakes": ["假设全是鸡时结果是兔的只数（设鸡得兔）", "脚数差除以2算错", "变种问题未正确识别脚数和头数", "方程法列错方程"],
    },
}


# 语文知识点详细模板
_CHINESE_DETAIL = {
    "修辞手法": {
        "definition": "修辞手法是通过修饰、调整语句，运用特定的表达形式以提高语言表达作用的方式和方法。",
        "key_points": [
            "比喻：用跟甲事物有相似之点的乙事物来描写或说明甲事物，包括明喻、暗喻、借喻",
            "拟人：把事物人格化，将本来不具备人动作和感情的事物变成和人一样具有动作和感情的样子",
            "排比：把三个或以上结构和长度均类似、语气一致、意义相关或相同的句子排列起来",
            "夸张：为了达到某种表达效果，对事物的形象、特征、作用、程度等方面着意夸大或缩小",
            "反问：用疑问的句式表达肯定的观点，只问不答，答案暗含在反问句中",
            "设问：为了强调某部分内容，故意先提出问题，明知故问，自问自答",
            "对偶：用字数相等、结构相同、意义对称的一对短语或句子来表达两个相对应或相近意思",
            "反复：根据表达需要，有意让一个句子或词语重复出现",
        ],
        "formulas": [
            "比喻：本体 + 比喻词 + 喻体（明喻：像、好像、仿佛；暗喻：是、成为；借喻：只出现喻体）",
            "拟人：事物 + 人的动作/神态/语言",
            "排比：三个或以上结构相似的句子/短语",
        ],
        "examples": [
            "比喻：弯弯的月亮像一条小船（明喻）；那又浓又翠的景色，简直就是一幅青山绿水画（暗喻）",
            "拟人：风儿清唱着歌，唤醒了沉睡中的大地",
            "排比：爱心是一片照射在冬日的阳光，爱心是一泓出现在沙漠里的泉水，爱心是一首飘荡在夜空的歌谣",
            "夸张：飞流直下三千尺，疑是银河落九天",
            "反问：难道我们不应该珍惜时间吗？",
            "设问：什么是路？就是从没路的地方践踏出来的，从只有荆棘的地方开辟出来的",
        ],
        "methods": "修辞手法辨析法：1.看是否有比喻词和本体喻体（比喻）；2.看事物是否被赋予人的特征（拟人）；3.看是否有三个以上相似结构（排比）；4.看是否有夸大或缩小（夸张）；5.看是否有问无答表肯定（反问）或有问有答（设问）。",
        "common_mistakes": ["比喻和拟人混淆（比喻有本体喻体，拟人是赋予人的特征）", "排比和反复混淆（排比结构相似，反复是词语重复）", "反问和设问混淆（反问只问不答表肯定，设问自问自答）", "夸张和比喻混淆（夸张是夸大缩小，比喻是打比方）"],
    },
    "记叙文六要素": {
        "definition": "记叙文六要素是指时间、地点、人物、事件的起因、经过、结果，是记叙文的基本构成要素。",
        "key_points": [
            "时间：事件发生的时间，可以是具体时间（某年某月某日）或模糊时间（很久以前、有一天）",
            "地点：事件发生的地点，可以是具体地点或泛指地点",
            "人物：事件中的主要人物和次要人物",
            "起因：事件发生的原因和背景",
            "经过：事件发展的过程，是记叙文的主体部分",
            "结果：事件的结局和影响",
            "六要素不一定都明确出现，有时可以省略某些要素",
        ],
        "formulas": [
            "概括主要内容公式：谁 + 在什么时间 + 什么地点 + 做了什么事 + 结果如何",
            "六要素串联法：时间 + 地点 + 人物 + 起因 + 经过 + 结果",
        ],
        "examples": [
            "例：《狼牙山五壮士》时间：1941年秋；地点：狼牙山；人物：五壮士（马宝玉、葛振林、宋学义、胡德林、胡福才）；起因：为掩护群众和连队转移；经过：诱敌上山、英勇杀敌、跳崖；结果：英勇跳崖，两人生还",
            "概括主要内容：1941年秋，八路军某部七连六班的五个战士，为了掩护群众和连队转移，把敌人引上狼牙山顶峰，英勇杀敌，最后英勇跳崖。",
        ],
        "methods": "六要素提取法：1.通读全文，找出表示时间的词语；2.找出表示地点的词语；3.找出主要人物；4.找出事件的起因（为什么做）；5.找出事件的经过（怎么做的）；6.找出事件的结果（做得怎样）。概括时用简洁的语言把六要素串联起来。",
        "common_mistakes": ["概括时遗漏重要要素", "经过部分概括不完整或过于啰嗦", "把次要人物当成主要人物", "起因和结果混淆"],
    },
}

# ============================================================
# 语文知识点类别详情库 —— 每个类别都有实质性教学内容
# ============================================================
_CHINESE_CATEGORY = {
    "拼音": {
        "definition": "汉语拼音是中华人民共和国官方颁布的汉字注音拉丁化方案，用于给汉字注音、推广普通话、字典排序和中文输入。",
        "key_points": [
            "声母23个：b p m f d t n l g k h j q x zh ch sh r z c s y w",
            "韵母24个：单韵母6个(a o e i u ü)、复韵母9个(ai ei ui ao ou iu ie üe er)、前鼻韵母5个(an en in un ün)、后鼻韵母4个(ang eng ing ong)",
            "整体认读音节16个：zhi chi shi ri zi ci si yi wu yu ye yue yuan yin yun ying",
            "声调4个：一声(ˉ)平、二声(ˊ)升、三声(ˇ)拐弯、四声(ˋ)降，轻声不标调",
            "拼写规则：j q x y 和 ü 相拼时 ü 上两点要去掉；a o e 开头的音节连在其他音节后面时用隔音符号隔开",
            "标调规则：有a不放过，没a找o e，i u并列标在后，i上标调把点抹，轻声不标就空着",
        ],
        "formulas": [
            "标调口诀：有a先找a，没a找o e，i u都有标在后，i上标调点去掉",
            "ü上两点省略口诀：j q x y真淘气，见到ü眼就挖去",
            "音节 = 声母 + 韵母 + 声调（零声母音节只有韵母和声调）",
        ],
        "examples": [
            "例1：中的拼音是 zhōng（声母zh + 韵母ong + 一声）",
            "例2：学的拼音是 xué（声母x + 韵母üe + 二声，ü上两点去掉）",
            "例3：西安拼音是 xī an（两个音节，用隔音符号隔开，否则会读成 xiān先）",
            "例4：整体认读音节 zhi chi shi ri 不用拼，直接整体认读",
        ],
        "methods": "拼音学习四步法：1.读准声母韵母（发音部位要准确，平舌音zcs舌尖抵上齿背，翘舌音zhchsh舌尖抵硬腭前部）；2.掌握拼读方法（两拼法：声母轻短韵母重，两音相连猛一碰；三拼法：声轻介快韵母响，三音连读很顺当）；3.熟记标调规则；4.在识字和阅读中巩固运用。",
        "common_mistakes": ["平翘舌音不分（z/zh、c/ch、s/sh混淆）", "前后鼻音不分（an/ang、en/eng、in/ing混淆）", "n/l不分、f/h不分（方言影响）", "标调位置错误（i u并列时应标在后一个上）", "ü上两点该省不省或不该省乱省"],
    },
    "偏旁": {
        "definition": "偏旁是合体字的构字部件，部首是字典中根据汉字字形结构归类的偏旁，是查字典的重要依据。笔顺是汉字笔画的书写顺序。",
        "key_points": [
            "常见偏旁部首：亻(单人旁)、氵(三点水)、扌(提手旁)、木(木字旁)、艹(草字头)、宀(宝盖头)、辶(走之底)、阝(双耳旁)、忄(竖心旁)、讠(言字旁)、纟(绞丝旁)、饣(食字旁)、犭(反犬旁)、礻(示字旁)、衤(衣字旁)",
            "偏旁表义规律：氵多与水有关(江、河、海)，扌多与手的动作有关(打、拉、推)，木多与树木有关(树、林、桃)，艹多与植物有关(花、草、苗)，讠多与说话有关(说、话、语)",
            "笔顺基本规则：先横后竖(十)、先撇后捺(人)、从上到下(三)、从左到右(川)、先外后内(月)、先中间后两边(小)、先外后内再封口(国)",
            "特殊笔顺：匕先撇后竖弯钩，乃先横折折折钩后撇，及先撇后横折折撇再捺，方点横横折钩撇",
            "汉字笔画28种：基本笔画5种(横竖撇捺折)，派生笔画23种(提、竖钩、弯钩、卧钩、竖折、横折、撇折等)",
        ],
        "formulas": [
            "笔顺口诀：从上到下，从左到右，先横后竖，先撇后捺，先外后内，先中间后两边，先里头后封口",
            "偏旁表义口诀：三点水旁水相关，提手旁儿手有关，木字旁儿树木连，草字头儿植物繁，言字旁儿说话谈",
        ],
        "examples": [
            "例1：河是左右结构，氵(三点水)+可，与水有关",
            "例2：打是左右结构，扌(提手旁)+丁，与手的动作有关",
            "例3：花是上下结构，艹(草字头)+化，与植物有关",
            "例4：国的笔顺：竖、横折、横、横、竖、横、点、横（先外后内再封口）",
            "例5：小的笔顺：竖钩、撇、点（先中间后两边）",
        ],
        "methods": "偏旁部首学习法：1.归类记忆（按表义规律归类，如氵类字都与水有关）；2.对比辨析（形近偏旁对比，如礻/衤、冫/氵、日/目）；3.查字典练习（用部首查字法查字，巩固部首知识）；4.在识字中积累（每学生字都分析其偏旁部首和表义功能）。笔顺学习要严格按规则书写，多写多练，注意特殊字的笔顺。",
        "common_mistakes": ["形近偏旁混淆（礻/衤、冫/氵、日/目、夂/攵）", "笔顺错误（忄先点后点再竖，不是先竖后两点；火先点撇再撇捺）", "部首判断错误（思的部首是心不是田，辨的部首是辛）", "写错笔画名称（把提说成横，把竖钩说成竖）"],
    },
    "形近字": {
        "definition": "形近字是指字形结构相近的字，多音字是指一个字有两个或两个以上读音的字。辨析形近字和多音字是语文基础知识的重点。",
        "key_points": [
            "形近字类型：笔画相同位置不同(未/末)、字形相近笔形不同(己/已/巳)、字形相近偏旁不同(坡/波/披)、字形相近笔画不同(日/目)、字形相近读音相同(躁/燥)、字形相近读音不同(估/姑)",
            "多音字类型：词性不同读音不同(长：cháng形容词/zhǎng动词)、意义不同读音不同(重：zhòng重量/chóng重复)、语体不同读音不同(血：xuè书面/xiě口语)、普通用法与特殊用法(单：dān普通/chán单于/shàn姓)",
            "辨析方法：从字音、字形、字义三方面辨析，结合词语语境判断",
            "常见形近字组：己/已/巳、未/末、戊/戌/戍/戎、拔/拨、辩/辨/辫/瓣、燥/躁/噪/澡、栽/裁/载/戴、即/既、折/拆/析、徒/徙/陡",
            "常见多音字：长、重、行、乐、着、了、和、差、强、模、处、好、空、背、盛、倒、当、发、还",
        ],
        "formulas": [
            "形近字辨析口诀：辨字形，看偏旁，表义功能记心上；比笔画，数多少，细微差别别忘掉；读字音，想字义，结合语境辨仔细",
            "多音字辨析口诀：多音字，不可怕，词性义项语体差；结合词语来判断，语境之中定读音",
        ],
        "examples": [
            "例1：己/已/巳——己(jǐ)自己，已(yǐ)已经，巳(sì)巳时（口诀：张口己，半口已，闭口巳）",
            "例2：拔/拨——拔(bá)拔草（右边是犮，多一点），拨(bō)拨打（右边是发，少一点）",
            "例3：辩/辨/辫/瓣——辩(biàn)辩论（中间讠，用嘴说），辨(biàn)辨别（中间刂，用刀分），辫(biàn)辫子（中间纟，用丝编），瓣(bàn)花瓣（中间瓜，与瓜有关）",
            "例4：行——xíng行走（动词），háng银行（名词），héng道行（口语）",
            "例5：着——zhe看着（助词），zháo着急（动词），zhuó穿着（动词），zhāo着数（名词）",
        ],
        "methods": "形近字辨析五法：1.偏旁辨析法（根据偏旁表义功能区分，如躁足字旁与心情急躁有关，燥火字旁与干燥有关）；2.笔画辨析法（数笔画多少，如未横短撇长，末横长撇短）；3.口诀记忆法（自编口诀帮助记忆，如己已巳口诀）；4.语境辨析法（把字放在词语中辨析）；5.归类整理法（把形近字归类整理，对比记忆）。多音字要注意积累常见多音字的不同读音和用法。",
        "common_mistakes": ["形近字混淆（把辨别写成辩别，把拔草写成拨草）", "多音字读错（把银行读成yín xíng，把着急读成zhuó jí）", "只看字形不看字义（凭印象判断，不结合语境）", "忽略特殊读音（只记常见读音，忽略罕见读音）"],
    },
    "查字典": {
        "definition": "查字典是学习语文的基本技能，常用方法有音序查字法、部首查字法和数笔画查字法，适用于不同的查字需求。",
        "key_points": [
            "音序查字法：知道读音但不知道字义时用。步骤：①读准字音，确定音节的第一个字母（音序，大写）；②在汉语拼音音节索引中找到这个字母，再找音节；③按页码翻到正文，找到要查的字",
            "部首查字法：知道字形但不知道读音时用。步骤：①确定部首，数部首笔画；②在部首目录中找到部首和页码；③在检字表中找到部首，数除部首外的笔画数，找到字和页码；④按页码翻到正文找到字",
            "数笔画查字法：不知道读音也难以确定部首时用。步骤：①数准字的总笔画数；②在难检字笔画索引中按笔画数找到字；③按页码翻到正文找到字",
            "确定部首的方法：左右结构查左边，上下结构查上边，内外结构查外边，独体字查起笔或整个字",
            "字典中字的排列：按音序排列，同音字按笔画数由少到多排列，同笔画按起笔横竖撇捺折排列",
        ],
        "formulas": [
            "音序查字法口诀：音序查字先记牢，读准字音很重要；找到音序找音节，翻到页码字找到",
            "部首查字法口诀：部首查字有四步，先找部首批一数；部首目录找页码，检字表中再数除；找到页码翻正文，要查的字就在乎",
            "数笔画查字法口诀：难检字，不用慌，数准笔画是关键；难检字表按笔画，找到页码翻正文",
        ],
        "examples": [
            "例1：用音序查字法查础——读准chǔ，音序C，在音节索引中找C→chu→翻到页码→找到础",
            "例2：用部首查字法查鸿——确定部首氵(3画)，部首目录找氵→检字表找氵部→除部首外8画→找到鸿→翻页码",
            "例3：用数笔画查字法查毋——独体字难定部首，数总笔画4画→难检字表4画→找到毋",
            "例4：闻是内外结构，部首查门不是耳；辨是左中右结构，部首查辛",
        ],
        "methods": "查字典练习法：1.三种方法都要熟练掌握，根据不同情况选择合适方法（知道读音用音序法，知道字形用部首法，都不知道用数笔画法）；2.多查多练，养成遇到生字就查字典的习惯；3.注意部首判断的特殊情况（如思查心不查田，鸣查口不查鸟）；4.查字典时不仅要找到字，还要认真看字义、组词、例句，真正理解字的用法。",
        "common_mistakes": ["音序写错（把小写字母当音序，音序必须是大写字母）", "部首判断错误（左右结构查了右边，上下结构查了下边）", "除部首外笔画数错（数笔画时把部首笔画也算进去，或漏数笔画）", "音节找错（声调不同但音节相同，要仔细找）", "只查不看（找到字就完事，不看字义和用法）"],
    },
    "近义词": {
        "definition": "近义词是指词汇意义相同或相近的词语，反义词是指词汇意义相反或相对的词语。辨析近义词和反义词是词语运用的基础。",
        "key_points": [
            "近义词辨析角度：词义轻重（损坏/破坏）、范围大小（时代/时期）、适用对象（爱戴/爱护）、感情色彩（果断/武断）、语体色彩（吓唬/恐吓）、搭配习惯（发扬/发挥）、词性语法（突然/忽然）",
            "反义词类型：绝对反义词（生/死、真/假，非此即彼）、相对反义词（黑/白、大/小，中间有中间状态）、成对反义词（上/下、前/后，表示对应关系）",
            "找反义词方法：在原词前加不找近义词（如好→不好→坏）、从词的反义义项找、结合具体语境找",
            "常见近义词组：屹立/矗立/耸立、改进/改善、必须/必需、截止/截至、爆发/暴发、反应/反映、启事/启示、权利/权力",
            "常见反义词组：真/假、善/恶、美/丑、爱/恨、贫/富、贵/贱、荣/辱、生/死、优/劣、胜/败",
        ],
        "formulas": [
            "近义词辨析公式：词义+词性+色彩+搭配+对象+范围+轻重+语体",
            "反义词寻找公式：原词→加不→找近义→定反义",
        ],
        "examples": [
            "例1：屹立/矗立/耸立——屹立：坚定不可动摇（形容人或物）；矗立：高耸直立（形容建筑物）；耸立：高高地直立（形容山峰）",
            "例2：必须/必需——必须：副词，一定要（后接动词，如必须努力）；必需：动词，一定要有（后接名词，如必需品）",
            "例3：截止/截至——截止：动词，到一定期限停止（如报名已截止）；截至：介词，截止到某个时候（如截至本月底）",
            "例4：反应/反映——反应：名词/动词，受到刺激引起的活动或变化（如化学反应、反应强烈）；反映：动词，把情况意见告诉上级或表现出来（如反映情况、反映现实）",
            "例5：好的反义词——不好→坏、差、劣（结合语境：成绩好→差，人好→坏，质量好→劣）",
        ],
        "methods": "近义词辨析七步法：1.看词义轻重（程度深浅）；2.看范围大小（外延宽窄）；3.看适用对象（用于人还是物，用于上级还是下级）；4.看感情色彩（褒义/贬义/中性）；5.看语体色彩（书面/口语/文学）；6.看搭配习惯（与什么词搭配）；7.看词性语法（在句中作什么成分）。反义词要注意结合具体语境，一个词可能有多个反义词。",
        "common_mistakes": ["近义词只看字面不看细微差别（把必须和必需混用）", "反义词找得不恰当（找近义词当反义词，或找的词意义不相反）", "忽略感情色彩（把贬义词当褒义词用）", "忽略搭配习惯（发扬配传统/精神，发挥配作用/优势，不能混用）"],
    },
    "成语": {
        "definition": "成语是汉语中经过长期使用、锤炼而形成的固定短语，大多由四字组成，具有结构固定、意义整体、出处明确、感情色彩鲜明的特点。",
        "key_points": [
            "成语来源：历史故事（完璧归赵、负荆请罪）、寓言故事（守株待兔、亡羊补牢）、神话传说（精卫填海、夸父逐日）、古典作品（温故知新、学而不厌）、口语俗语（七上八下、三心二意）",
            "成语结构：并列结构（喜怒哀乐、酸甜苦辣）、偏正结构（一丘之貉、中流砥柱）、动宾结构（包罗万象、顾全大局）、主谓结构（毛遂自荐、夜郎自大）、连动结构（画蛇添足、刻舟求剑）、兼语结构（请君入瓮、引狼入室）",
            "成语感情色彩：褒义（鞠躬尽瘁、奋不顾身）、贬义（处心积虑、趋之若鹜）、中性（今非昔比、络绎不绝）",
            "成语运用注意：理解整体意义不能望文生义、注意适用对象和范围、注意感情色彩、注意与语境搭配、注意字形正确",
            "常见易错成语：不以为然（不认为对，不是不放在心上）、不孚众望（不能使人信服，不是不负众望）、首当其冲（最先受到攻击，不是冲在最前面）、炙手可热（权势大气焰盛，不是热门）、美轮美奂（形容房屋高大，不是美好）",
        ],
        "formulas": [
            "成语学习公式：出处+本义+引申义+感情色彩+适用对象+例句",
            "成语辨析公式：意义+对象+色彩+搭配+语境",
        ],
        "examples": [
            "例1：完璧归赵——出处：《史记·廉颇蔺相如列传》；本义：把和氏璧完好地送回赵国；引申义：把原物完好地归还本人；褒义；用于归还物品",
            "例2：守株待兔——出处：《韩非子》；本义：守在树桩旁等兔子撞死；引申义：不主动努力，存侥幸心理希望得到意外收获；贬义；用于批评不劳而获",
            "例3：不以为然——然：对。不认为是对的，表示不同意（多含轻视意）。不能理解为不放在心上/不屑一顾（那是不以为意）",
            "例4：不孚众望——孚：信服。不能使大家信服。与不负众望（不辜负大家的期望）意思相反，不能混用",
            "例5：首当其冲——冲：要冲，交通要道。比喻最先受到攻击或遭到灾难。不能理解为冲在最前面/首要位置",
        ],
        "methods": "成语学习五步法：1.追本溯源（了解成语出处和故事，帮助理解意义）；2.理解整体（成语意义是整体的，不能逐字翻译望文生义）；3.辨析色彩（分清褒义贬义中性）；4.明确对象（知道成语适用于什么人什么事）；5.语境运用（在具体语境中正确使用，注意搭配）。建议建立成语积累本，分类整理，定期复习。",
        "common_mistakes": ["望文生义（只按字面意思理解，如把首当其冲理解为冲在最前面）", "褒贬误用（把贬义词当褒义词用，如处心积虑用于褒义）", "对象误用（用错对象，如美轮美奂用于形容风景）", "谦敬错位（谦辞用于对方，敬辞用于自己，如抛砖引玉用于对方）", "形近混淆（把不孚众望和不负众望混用）"],
    },
    "关联词": {
        "definition": "关联词是在复句中用来连接分句并表明分句之间关系的词语，包括连词、副词和部分短语。正确使用关联词是句子表达的基础。",
        "key_points": [
            "并列关系：又……又……、既……又……、一边……一边……、那么……那么……、是……也是……、不是……而是……",
            "递进关系：不但……而且……、不仅……还……、不但不……反而……、连……也……、何况……、甚至……",
            "选择关系：不是……就是……、或者……或者……、要么……要么……、与其……不如……、宁可……也不……",
            "转折关系：虽然……但是……、尽管……可是……、……然而……、……却……",
            "因果关系：因为……所以……、由于……因此……、既然……那么……、之所以……是因为……",
            "假设关系：如果……就……、要是……那么……、即使……也……、哪怕……也……",
            "条件关系：只要……就……、只有……才……、无论……都……、不管……总……、除非……才……",
            "承接关系：首先……然后……、……便……、……于是……、……才……、……接着……",
        ],
        "formulas": [
            "关联词使用公式：判断关系→选择关联词→检查搭配→验证逻辑",
            "关联词配对口诀：虽然但是配成对，因为所以表因果，如果就是表假设，只有才表条件，不但而且表递进，不是就是表选择",
        ],
        "examples": [
            "例1：并列关系——他既会唱歌，又会跳舞。（两个分句并列，不分主次）",
            "例2：递进关系——他不但学习好，而且品德好。（后一分句比前一分句意思更进一层）",
            "例3：转折关系——虽然天气很冷，但是同学们都坚持锻炼。（后一分句与前一分句意思相反或相对）",
            "例4：因果关系——因为他平时努力学习，所以考试取得了好成绩。（前一分句是原因，后一分句是结果）",
            "例5：假设关系——如果明天下雨，运动会就延期举行。（前一分句提出假设，后一分句说明假设实现后的结果）",
            "例6：条件关系——只有努力学习，才能取得好成绩。（前一分句提出条件，后一分句说明在这个条件下产生的结果）",
        ],
        "methods": "关联词使用四步法：1.判断关系（分析前后分句之间是什么逻辑关系：并列/递进/选择/转折/因果/假设/条件/承接）；2.选择关联词（根据关系选择恰当的关联词，注意关联词的配对使用）；3.检查搭配（关联词是否配对正确，如虽然配但是不能配所以）；4.验证逻辑（读整个句子，看逻辑是否通顺，意思是否明确）。注意：有些关联词可以省略，有些必须配对使用；关联词的位置要正确（主语相同关联词在主语后，主语不同关联词在主语前）。",
        "common_mistakes": ["关联词搭配不当（虽然配所以，应为虽然……但是……）", "关联词误用（因果关系用了转折关联词，递进关系用了并列关联词）", "关联词位置不当（主语相同时关联词放在主语前，如不但他学习好，而且品德好应为他不但学习好，而且品德好）", "滥用关联词（不需要关联词的地方硬加，使句子啰嗦）", "漏用关联词（该用关联词的地方不用，使句子关系不明确）"],
    },
    "句式转换": {
        "definition": "句式转换是指在不改变句子基本意思的前提下，把一种句式变换成另一种句式，包括陈述句与反问句互换、把字句与被字句互换、肯定句与双重否定句互换、直接引语与间接引语互换等。",
        "key_points": [
            "陈述句改反问句：①加反问词（难道、怎么、怎能）；②加否定词（不、没有）或去掉否定词；③加语气词（吗、呢）；④句号改问号；⑤检查意思不变",
            "反问句改陈述句：①去掉反问词；②去掉或加上否定词；③去掉语气词；④问号改句号；⑤整理句子使通顺",
            "把字句改被字句：把把字前后的名词互换位置，把改成被，其他成分不变",
            "被字句改把字句：把被字前后的名词互换位置，被改成把，其他成分不变",
            "肯定句改双重否定句：在谓语动词前加双重否定词（不得不、不能不、不会不、不是不、非……不可、没有一个不），注意不改变原意",
            "直接引语改间接引语：①改标点（冒号改逗号，去掉引号）；②改人称（第一人称改第三人称，第二人称根据语境改）；③改时态（现在改过去，过去改过去完成）；④改指示代词（这改那，这里改那里）；⑤改趋向动词（来改去）",
        ],
        "formulas": [
            "陈述句改反问句公式：加反问词+加/去否定词+加语气词+改问号",
            "把被互换公式：把/被前后名词互换+把改被/被改把+其余不变",
            "直接引语改间接引语公式：改标点+改人称+改时态+改指示代词+改趋向动词",
        ],
        "examples": [
            "例1：陈述句改反问句——我们不能浪费时间。→我们怎么能浪费时间呢？（加反问词怎么，去掉否定词不，加语气词呢，改问号）",
            "例2：反问句改陈述句——难道这不是伟大的奇观吗？→这是伟大的奇观。（去掉反问词难道，去掉否定词不，去掉语气词吗，改句号）",
            "例3：把字句改被字句——雨水把衣服淋湿了。→衣服被雨水淋湿了。（雨水和衣服互换，把改被）",
            "例4：肯定句改双重否定句——他一定来。→他不会不来。或他非来不可。（加双重否定词，意思不变）",
            "例5：直接引语改间接引语——小明说：我明天去图书馆。→小明说，他第二天去图书馆。（冒号改逗号，去引号，我改他，明天改第二天）",
        ],
        "methods": "句式转换五步法：1.读懂原句（理解原句的意思和结构）；2.明确目标（确定要转换成什么句式）；3.按规则转换（根据不同句式的转换规则逐步转换）；4.检查意思（转换后的句子意思必须与原句基本一致，不能改变原意）；5.整理通顺（调整词语使句子通顺，标点正确）。注意：句式转换只改变句子形式，不改变句子意思；要注意特殊情况（如反问句本身是否定的，改陈述句时要去掉否定词）。",
        "common_mistakes": ["改变原意（转换后意思与原句相反，如陈述句改反问句时否定词加减错误）", "标点错误（反问句用句号，陈述句用问号）", "人称错误（直接引语改间接引语时人称改错）", "时态错误（直接引语改间接引语时时态没有相应改变）", "双重否定词用错（用了一个否定词变成否定句，不是双重否定）"],
    },
    "病句": {
        "definition": "病句是指在语法或逻辑上有毛病的句子，即不符合现代汉语表达规则或违反客观事理的句子。辨析和修改病句是语文基础知识的重点和难点。",
        "key_points": [
            "病句六大类型：①语序不当（定语/状语语序不当、关联词语位置不当、主客颠倒）；②搭配不当（主谓/动宾/主宾/修饰语与中心语/一面与两面/否定与肯定搭配不当）；③成分残缺或赘余（缺主语/谓语/宾语/中心语，成分赘余重复啰嗦）；④结构混乱（句式杂糅、中途易辙、藕断丝连）；⑤表意不明（指代不明、有歧义、修饰对象不明）；⑥不合逻辑（自相矛盾、范围不清、强加因果、主客倒置、否定不当、不合事理）",
            "辨析方法：①语感审读法（读句子，凭语感判断别扭的地方）；②主干枝叶梳理法（先找主谓宾主干，再看定状补枝叶）；③造句类比法（仿照原句结构造常用句子比较）；④逻辑分析法（从概念、判断、推理角度分析是否合理）",
            "修改原则：保留原意、多就少改、不改变句意、尽量不增删词语",
            "修改方法：增（残缺的成分补上）、删（多余的成分删去）、调（语序不当的调换）、换（搭配不当的替换）",
            "常见标志词：看到通过……使……想缺主语，看到能否/是否/好坏想一面两面，看到避免/防止/杜绝想否定不当，看到大约/左右/上下想重复，看到和/与/跟想歧义或搭配",
        ],
        "formulas": [
            "病句辨析公式：读语感→找主干→看枝叶→查逻辑→定类型",
            "病句修改公式：增残缺+删赘余+调语序+换搭配",
            "常见病句标志口诀：通过使缺主语，能否是否两面失，避免防止否定乱，大约左右重复计，和与跟字歧义生",
        ],
        "examples": [
            "例1（成分残缺）：通过这次活动，使我明白了团结的重要。——缺主语，删通过或使。改：这次活动使我明白了团结的重要。或通过这次活动，我明白了团结的重要。",
            "例2（搭配不当）：他的写作水平明显改进了。——主谓搭配不当，水平不能改进，应提高。改：他的写作水平明显提高了。",
            "例3（语序不当）：我们要认真克服并发现工作中的缺点。——逻辑语序不当，应先发现后克服。改：我们要认真发现并克服工作中的缺点。",
            "例4（不合逻辑/一面两面）：能否刻苦学习是取得好成绩的关键。——一面两面不搭配，能否是两面，取得好成绩是一面。改：刻苦学习是取得好成绩的关键。或能否刻苦学习是能否取得好成绩的关键。",
            "例5（否定不当）：为了防止这类事故不再发生，我们加强了安全教育。——防止已含否定意，再加不变成肯定，意思反了。改：为了防止这类事故再发生，我们加强了安全教育。",
            "例6（句式杂糅）：这篇文章的作者是老舍先生写的。——作者是老舍和是老舍先生写的两句杂糅。改：这篇文章的作者是老舍先生。或这篇文章是老舍先生写的。",
        ],
        "methods": "病句辨析修改四步法：1.读（默读句子，凭语感找别扭的地方，不通顺的地方往往是病处）；2.找（找句子主干主谓宾，看主干是否残缺或搭配不当；再看枝叶定状补，看修饰是否恰当）；3.析（分析逻辑关系，看是否合事理、有无矛盾、一面两面是否搭配、否定是否恰当）；4.改（根据病句类型用增删调换方法修改，保留原意，多就少改）。建议多做病句练习，总结常见类型和标志词，提高敏感度。",
        "common_mistakes": ["找不出病因（凭感觉乱改，没有准确判断病句类型）", "修改后改变原意（把正确的地方改错了，或改变了句子本来意思）", "修改过度（大删大改，没有遵循多就少改原则）", "忽略逻辑错误（只看语法不看逻辑，如一面两面、否定不当、自相矛盾）", "修改不彻底（只改了一处，还有其他语病没改）"],
    },
    "修辞": {
        "definition": "修辞手法是通过修饰、调整语句，运用特定的表达形式以提高语言表达作用的方式和方法。常见的修辞手法有比喻、拟人、排比、夸张、反问、设问、对偶、反复等。",
        "key_points": [
            "比喻：用跟甲事物有相似之点的乙事物来描写或说明甲事物，包括明喻（像、好像、仿佛）、暗喻（是、成为）、借喻（只出现喻体）",
            "拟人：把事物人格化，将本来不具备人动作和感情的事物变成和人一样具有动作和感情的样子",
            "排比：把三个或以上结构和长度均类似、语气一致、意义相关或相同的句子排列起来，增强语势",
            "夸张：为了达到某种表达效果，对事物的形象、特征、作用、程度等方面着意夸大或缩小",
            "反问：用疑问的句式表达肯定的观点，只问不答，答案暗含在反问句中，加强语气",
            "设问：为了强调某部分内容，故意先提出问题，明知故问，自问自答，引起注意和思考",
            "对偶：用字数相等、结构相同、意义对称的一对短语或句子来表达两个相对应或相近意思，整齐匀称",
            "反复：根据表达需要，有意让一个句子或词语重复出现，强调某种意思，突出某种情感",
        ],
        "formulas": [
            "比喻：本体 + 比喻词 + 喻体（明喻：像、好像、仿佛；暗喻：是、成为；借喻：只出现喻体）",
            "拟人：事物 + 人的动作/神态/语言",
            "排比：三个或以上结构相似的句子/短语",
            "夸张：夸大或缩小事物特征",
            "反问：只问不答表肯定/否定",
            "设问：自问自答",
        ],
        "examples": [
            "例1（比喻）：弯弯的月亮像一条小船（明喻）；那又浓又翠的景色，简直就是一幅青山绿水画（暗喻）",
            "例2（拟人）：风儿清唱着歌，唤醒了沉睡中的大地",
            "例3（排比）：爱心是一片照射在冬日的阳光，爱心是一泓出现在沙漠里的泉水，爱心是一首飘荡在夜空的歌谣",
            "例4（夸张）：飞流直下三千尺，疑是银河落九天",
            "例5（反问）：难道我们不应该珍惜时间吗？",
            "例6（设问）：什么是路？就是从没路的地方践踏出来的，从只有荆棘的地方开辟出来的",
        ],
        "methods": "修辞手法辨析法：1.看是否有比喻词和本体喻体（比喻）；2.看事物是否被赋予人的特征（拟人）；3.看是否有三个以上相似结构（排比）；4.看是否有夸大或缩小（夸张）；5.看是否有问无答表肯定（反问）或有问有答（设问）；6.看是否字数相等结构对称（对偶）；7.看是否有词语句子重复（反复）。赏析时要答出手法+内容+表达效果。",
        "common_mistakes": ["比喻和拟人混淆（比喻有本体喻体，拟人是赋予人的特征）", "排比和反复混淆（排比结构相似，反复是词语重复）", "反问和设问混淆（反问只问不答表肯定，设问自问自答）", "夸张和比喻混淆（夸张是夸大缩小，比喻是打比方）", "赏析题只说手法不说效果（要答手法+内容+效果）"],
    },
    "标点": {
        "definition": "标点符号是书面语中用来表示停顿、语气以及词语的性质和作用的符号，是书面语的有机组成部分。标点符号分为点号和标号两大类。",
        "key_points": [
            "点号（表示停顿和语气）：句号（。）陈述句末尾；问号（？）疑问句末尾；感叹号（！）感叹句末尾；逗号（，）句子内部停顿；顿号（、）并列词语之间；分号（；）并列分句之间；冒号（：）提示下文或总结上文",
            "标号（表示词语性质和作用）：引号（''""）引用、特定称谓、强调、讽刺否定；括号（（）[]）注释说明；破折号（——）解释说明、话题转换、声音延长、意思递进；省略号（……）内容省略、说话断续、语意未尽；书名号（《》<>）书籍篇章报刊歌曲等名称；着重号（.）强调；间隔号（·）人名书名之间；连接号（—-）时间地点数目之间；专名号（___）人名地名朝代名",
            "引号用法：直接引用、特定称谓、强调突出、讽刺否定、特殊含义。注意：引用之语未独立，标点符号引号外；引用之语能独立，标点符号引号内",
            "破折号用法：解释说明、话题转换、声音延长、意思递进、总结上文、插说",
            "省略号用法：引文省略、列举省略、说话断续、语意未尽、沉默不语。注意：省略号不能与等等连用",
            "顿号用法：并列词语之间用顿号，并列短语之间用逗号，并列分句之间用分号。注意：约数之间不用顿号（三四米），确数之间用顿号（三、四组）",
        ],
        "formulas": [
            "点号停顿长短：句号/问号/感叹号 > 分号 > 逗号 > 顿号",
            "引号引用规则：独立引用标点在内，非独立引用标点在外",
            "顿号使用规则：并列词语用顿号，并列短语用逗号，并列分句用分号",
            "省略号使用规则：省略号不与等连用",
        ],
        "examples": [
            "例1（句号）：北京是中华人民共和国的首都。",
            "例2（问号）：你今天去图书馆吗？",
            "例3（感叹号）：多么美丽的风景啊！",
            "例4（顿号）：桃树、杏树、梨树，你不让我，我不让你，都开满了花赶趟儿。",
            "例5（分号）：语言，人们用来抒情达意；文字，人们用来记言记事。",
            "例6（冒号）：北京紫禁城有四座城门：午门、神武门、东华门和西华门。",
            "例7（引号）：他说：今天天气真好。（独立引用，句号在引号内）；写文章要做到平字见奇，常字见险。（非独立引用，句号在引号外）",
            "例8（破折号）：迈进金黄色的大门，穿过宽阔的风门厅和衣帽厅，就到了大会堂建筑的枢纽部分——中央大厅。（解释说明）",
            "例9（省略号）：她轻轻地哼起了《摇篮曲》：月儿明，风儿静，树叶儿遮窗棂啊……（引文省略）",
        ],
        "methods": "标点符号学习法：1.分类记忆（点号7种+标号9种，分类记忆用法）；2.例句学习（每种标点都记几个典型例句，帮助理解用法）；3.对比辨析（易混标点对比，如顿号/逗号/分号的区别，引号/破折号/冒号的区别）；4.规则总结（总结常见规则，如引号引用规则、省略号不与等连用、约数不用顿号等）；5.在阅读写作中练习（阅读时注意标点用法，写作时正确使用标点）。",
        "common_mistakes": ["顿号逗号分号混用（并列词语该用顿号用了逗号，并列分句该用分号用了逗号）", "引号标点位置错误（独立引用标点放在引号外，非独立引用放在引号内）", "省略号与等连用（苹果、香蕉、橘子等……错误，应去掉省略号或去掉等）", "约数之间用顿号（三、四个错误，应为三四个）", "书名号误用（活动主题、课程名称、考试名称不用书名号，应用引号）", "冒号滥用（一个句子中不能出现两个冒号）"],
    },
    "记叙文": {
        "definition": "记叙文是以叙述为主要表达方式，以写人物的经历和事物发展变化为主要内容的一种文体。记叙文阅读是语文阅读的基础和重点。",
        "key_points": [
            "记叙文六要素：时间、地点、人物、事件的起因、经过、结果",
            "记叙顺序：顺叙（按事情发展先后顺序）、倒叙（先写结果或高潮，再写起因经过）、插叙（在叙述中心事件过程中插入相关内容）、补叙（补充说明）、平叙（平行叙述两件或多件事）",
            "记叙人称：第一人称（我/我们，真实亲切，便于抒情）、第二人称（你/你们，亲切自然，便于交流）、第三人称（他/她/它/他们，客观全面，不受时空限制）",
            "人物描写方法：外貌描写（肖像/神态）、语言描写、动作描写、心理描写、细节描写",
            "环境描写：自然环境（景物描写，渲染气氛、烘托心情、推动情节、暗示主题）、社会环境（交代时代背景、社会风俗、思想观念）",
            "记叙文线索：人物线索、事件线索、物品线索、时间线索、地点线索、感情线索",
            "表达方式：记叙、描写、抒情、议论、说明",
            "表现手法：象征、对比、衬托、铺垫、伏笔、照应、悬念、抑扬、托物言志、借景抒情、虚实结合、动静结合",
        ],
        "formulas": [
            "概括主要内容公式：谁 + 在什么情况下 + 做了什么事 + 结果如何",
            "概括中心思想公式：本文记叙了……（内容），表现了/赞扬了/揭示了……（中心）",
            "人物形象分析公式：身份/性格 + 具体事例 + 作者态度",
            "句段作用公式：内容作用（写了什么/表现什么）+ 结构作用（开头/中间/结尾的不同作用）",
            "环境描写作用公式：渲染……气氛 + 烘托……心情 + 推动……情节 + 暗示……主题",
        ],
        "examples": [
            "例1（六要素）：《散步》时间：初春；地点：田野；人物：我、母亲、妻子、儿子；起因：一家人去散步；经过：走大路还是小路产生分歧；结果：我背母亲，妻子背儿子，走小路",
            "例2（人物描写）：他用两手攀着上面，两脚再向上缩；他肥胖的身子向左微倾，显出努力的样子。——动作描写，表现父亲爬月台的艰难，体现深沉的父爱",
            "例3（环境描写）：天边仿佛有一片紫色的阴影从海里钻出来。那就是哲尔赛岛了。——环境描写，烘托人物失望沮丧的心情，推动情节发展",
            "例4（记叙顺序）：《背影》开头写我与父亲不相见已二年余了，我最不能忘记的是他的背影——倒叙，设置悬念，引出下文",
            "例5（句段作用）：开头句段作用——开篇点题、总领全文、设置悬念、引出下文、渲染气氛、奠定感情基调；中间句段作用——承上启下、过渡衔接、铺垫伏笔、照应前文；结尾句段作用——总结全文、点明中心、深化主题、照应开头、引人深思",
        ],
        "methods": "记叙文阅读五步法：1.通读全文，把握内容（写了什么人什么事）；2.理清脉络，把握顺序（记叙顺序、线索、段落层次）；3.分析人物，把握形象（描写方法、性格特征、作者态度）；4.品味语言，把握技巧（修辞手法、描写方法、表现手法、重点词句含义）；5.理解中心，把握主旨（中心思想、作者情感、写作目的）。答题时要结合具体文本，不能空谈概念，注意答题规范和要点齐全。",
        "common_mistakes": ["概括内容不完整（遗漏重要情节或人物）", "中心理解偏差（只看表面不看深层，或过度解读）", "人物分析片面（只看一个事例就下结论，不全面分析）", "作用题只答内容不答结构（或只答结构不答内容）", "赏析题只说手法不说效果（要答手法+内容+效果）", "脱离文本空谈（答案没有结合原文具体内容）"],
    },
    "概括": {
        "definition": "概括段意和主要内容是指用简洁准确的语言概括段落或文章的主要意思，是阅读理解的基本能力，也是考试的常见题型。",
        "key_points": [
            "概括段意方法：①找中心句法（段落中有中心句，直接摘引或改写）；②叠加法（段落有几层意思，把几层意思叠加起来）；③取主法（段落有主次之分，取主要意思舍去次要）；④提问法（用谁做了什么或什么怎么样提问，回答就是段意）",
            "概括主要内容方法：①题目扩展法（扩展题目就是主要内容）；②要素串联法（把六要素串联起来）；③段意合并法（把各段段意合并起来）；④重点罗列法（抓住重点段落和重点词句概括）；⑤问题回答法（回答谁在什么情况下做了什么事结果怎样）",
            "概括要求：准确（不能改变原意）、完整（不能遗漏要点）、简洁（语言简练不啰嗦）、通顺（语句通顺流畅）",
            "概括中心思想方法：①找中心句法（文章中有直接点明中心的句子）；②分析主要内容法（先概括主要内容，再分析作者写作目的）；③分析题目法（题目往往点明中心或暗示中心）；④分析开头结尾法（开头结尾往往点明中心）；⑤分析抒情议论句法（抒情议论句往往点明中心）",
            "中心思想格式：本文记叙了（描写了/说明了）……（内容），表现了（赞扬了/揭示了/抒发了）……（中心/情感）",
        ],
        "formulas": [
            "段意概括公式：谁 + 做什么（或什么 + 怎么样）",
            "主要内容概括公式：时间 + 地点 + 人物 + 起因 + 经过 + 结果（可适当省略次要要素）",
            "中心思想概括公式：内容概括 + 写作目的（表现/赞扬/揭示/抒发……）",
            "概括要求口诀：准确完整又简洁，语句通顺不改变",
        ],
        "examples": [
            "例1（段意）：段落写春天来了，小草绿了，花儿开了，小鸟在树上唱歌，小朋友们在草地上放风筝。——段意：春天来了，万物复苏，小朋友们快乐地玩耍。",
            "例2（主要内容）：《散步》主要内容：初春时节，我带着母亲、妻子和儿子在田野散步，在走大路还是小路的问题上产生分歧，最后我决定走小路并背着母亲，妻子背着儿子走过小路。",
            "例3（中心思想）：《散步》中心思想：本文通过记叙一家人散步的平凡小事，表现了一家人互敬互爱、和睦融洽的亲情，颂扬了中华民族尊老爱幼的传统美德。",
            "例4（题目扩展法）：《济南的冬天》——主要内容：描写了济南冬天温晴的天气特点和山、水等景物，表达了作者对济南冬天的喜爱和赞美。",
            "例5（找中心句法）：《桂林山水》开头人们都说：桂林山水甲天下。——中心句，点明桂林山水天下第一，全文围绕这句话展开。",
        ],
        "methods": "概括能力训练法：1.先读全文，整体感知（不要急于概括，先读懂文章写了什么）；2.划分段落，概括段意（先分部分概括段意，再合并段意概括主要内容）；3.抓住要素，串联成句（记叙文抓六要素，说明文抓说明对象和特征，议论文抓论点和论据）；4.删繁就简，语言精炼（去掉修饰性词语，保留核心信息）；5.检查验证（对照原文看是否准确完整，是否改变原意）。注意：不同文体概括方法不同，要灵活运用；概括时不要加入自己的主观评价，要客观概括内容。",
        "common_mistakes": ["概括不完整（遗漏重要情节或要点）", "概括不准确（改变原意或加入主观评价）", "语言不简洁（啰嗦重复，用了太多修饰性词语）", "段意和主要内容混淆（段意是段落意思，主要内容是全文意思）", "主要内容和中心思想混淆（主要内容是写了什么，中心思想是为什么写）", "以偏概全（只概括了部分段落的意思，不是全文主要内容）"],
    },
    "中心思想": {
        "definition": "中心思想是作者在文章中要表达的贯穿全文的核心，是提纲挈领的道理，是作者在文章中努力通过各种细节来阐明的中心议题。简单地说，中心思想就是作者要告诉我们的道理和内涵。",
        "key_points": [
            "中心思想的组成：文章主要内容 + 作者写作目的（表现什么/赞扬什么/揭示什么/抒发什么/批判什么）",
            "找中心思想的方法：①看题目（题目往往点明中心或暗示中心）；②看开头结尾（开头结尾往往点明中心，开篇点题/卒章显志）；③看抒情议论句（抒情议论句往往直接点明中心）；④看反复出现的词句（反复出现的词句往往与中心有关）；⑤分析主要内容（先概括主要内容，再分析作者写作目的）；⑥看写作背景（结合时代背景理解作者写作意图）",
            "不同文体中心思想特点：记叙文——表现人物品质/抒发情感/揭示道理；说明文——介绍事物特征/阐明事理；议论文——表明作者观点主张；散文——抒发作者情感/揭示人生哲理",
            "中心思想表述格式：本文通过记叙（描写/说明/论述）……（主要内容），表现了（赞扬了/揭示了/抒发了/说明了/论证了）……（中心思想）",
            "概括中心思想要求：准确（不能偏离文章本意）、完整（既要概括内容又要点明目的）、简洁（语言简练不啰嗦）",
        ],
        "formulas": [
            "中心思想公式：主要内容 + 写作目的（表现/赞扬/揭示/抒发/说明/论证……）",
            "记叙文中心公式：本文记叙了……（人/事），表现了……（品质/情感/道理）",
            "说明文中心公式：本文介绍了……（事物/事理），说明了……（特征/道理）",
            "议论文中心公式：本文论述了……（问题），论证了……（观点）",
            "散文中心公式：本文描写了……（景物/事物），抒发了……（情感/哲理）",
        ],
        "examples": [
            "例1（记叙文）：《散步》——本文通过记叙一家人在田野散步的平凡小事，表现了一家人互敬互爱、和睦融洽的亲情，颂扬了中华民族尊老爱幼的传统美德。",
            "例2（说明文）：《苏州园林》——本文介绍了苏州园林的建筑特点，说明了苏州园林务必使游览者无论站在哪个点上，眼前总是一幅完美的图画的总特征，表达了作者对苏州园林的赞美之情。",
            "例3（议论文）：《谈骨气》——本文通过列举文天祥、穷人、闻一多三个事例，论证了我们中国人是有骨气的这一中心论点，号召我们发扬骨气精神。",
            "例4（散文）：《春》——本文通过描绘春草图、春花图、春风图、春雨图、迎春图五幅画面，抒发了作者对春天的喜爱和赞美之情，表现了作者热爱生活、积极进取的人生态度。",
            "例5（找中心句）：《桂林山水》开头人们都说：桂林山水甲天下。——中心句，点明桂林山水天下第一，全文围绕这句话展开。",
        ],
        "methods": "中心思想概括五步法：1.通读全文，整体感知（读懂文章写了什么内容）；2.概括内容，提炼要点（用简洁语言概括文章主要内容）；3.寻找标志，定位中心（看题目、开头结尾、抒情议论句、反复词句）；4.分析目的，提炼中心（思考作者为什么写这篇文章，想告诉我们什么）；5.组织语言，规范表述（用本文通过……表现了……的格式表述）。注意：不同文体中心思想表述方式不同，要灵活运用；不要加入自己的主观评价，要客观概括作者的写作意图。",
        "common_mistakes": ["中心思想概括不完整（只概括了主要内容，没有点明写作目的）", "中心思想概括不准确（偏离文章本意，或加入自己的主观评价）", "把主要内容当中心思想（主要内容是写了什么，中心思想是为什么写，二者不同）", "中心思想过于笼统（只说表现了作者的思想感情，没有具体说是什么感情）", "以偏概全（只根据部分段落概括中心，没有从全文整体把握）"],
    },
    "说明方法": {
        "definition": "说明方法是写说明文时用简明扼要的语言把事物的实际情况恰如其分地表述出来的方法。常见的说明方法有举例子、列数字、作比较、打比方、分类别、下定义、作诠释、摹状貌、引资料、画图表等。",
        "key_points": [
            "举例子：举出实际事例来说明事物，使所要说明的事物具体化，以便读者理解。标志词：例如、比如、据说、譬如",
            "列数字：用具体的数据说明事物特征或事理，使说明更准确、更科学、更具体、更具说服力。标志词：数词、约数、确数",
            "作比较：将两种类别相同或不同的事物、现象加以比较来说明事物特征。标志词：比、和……相比、相对于、较",
            "打比方：利用两种不同事物之间的相似之处作比较，以突出事物的性状特点，增强说明的形象性和生动性。标志词：像、好像、仿佛、如同",
            "分类别：将被说明的对象，按照一定的标准划分成不同的类别，一类一类地加以说明。标志词：一类（种）……一类（种）……、分为……",
            "下定义：用简明的语言对某一概念的本质特征作规定性的说明。格式：甲是乙（甲和乙可以互换）",
            "作诠释：从一个侧面，就事物的某一个特点做些解释。格式：甲是乙（甲和乙不能互换）",
            "摹状貌：为了使被说明对象更形象、具体，可以进行状貌摹写。标志词：描写性语言",
            "引资料：为了使说明的内容更充实具体，可以引用一些文献资料、诗词、俗语、名人名言等。标志词：引用、据说、传说",
        ],
        "formulas": [
            "说明方法作用公式：方法 + 具体内容 + 效果词（准确/具体/生动/形象/条理清晰/科学严谨）",
            "举例子作用：通过举……的例子，具体真实地说明了……的特征，使说明更有说服力",
            "列数字作用：用具体的数据，准确科学地说明了……的特征，使说明更具体、更有说服力",
            "作比较作用：把……和……加以比较，突出强调了……的特征，使读者印象深刻",
            "打比方作用：把……比作……，生动形象地说明了……的特征，增强了文章的趣味性",
            "分类别作用：把……分成……类，条理清晰地说明了……的特征，使说明更有条理性",
            "下定义作用：准确简明地揭示了……的本质特征，使读者对概念有确切的了解",
        ],
        "examples": [
            "例1（举例子）：我国的石拱桥几乎到处都有。这些桥大小不一，形式多样，有许多是惊人的杰作。其中最著名的当推河北省赵县的赵州桥，还有北京丰台区的卢沟桥。——举赵州桥和卢沟桥的例子，具体说明中国石拱桥是惊人的杰作。",
            "例2（列数字）：赵州桥非常雄伟，全长50.82米，两端宽9.6米，中部略窄，宽9米。——用具体数字准确说明赵州桥的雄伟。",
            "例3（作比较）：永定河发水时，来势很猛，以前两岸河堤常被冲毁，但是这座桥却极少出事，足见它的坚固。——把卢沟桥和两岸河堤作比较，突出卢沟桥的坚固。",
            "例4（打比方）：石拱桥的桥洞成弧形，就像虹。——把石拱桥的桥洞比作虹，生动形象地说明石拱桥的形状特点。",
            "例5（分类别）：通常情况下，我们将垃圾分为可回收物、厨余垃圾、有害垃圾和其他垃圾四类。——分类别说明，条理清晰。",
            "例6（下定义）：统筹方法，是一种安排工作进程的数学方法。——下定义，准确揭示统筹方法的本质特征。",
        ],
        "methods": "说明方法辨析与作用分析法：1.熟记常见说明方法及标志词（举例子、列数字、作比较、打比方、分类别、下定义、作诠释、摹状貌、引资料）；2.根据标志词判断说明方法（注意区分打比方和比喻、作比较和对比、下定义和作诠释）；3.分析说明方法的作用（结合具体内容，用方法+内容+效果的格式）；4.注意多种说明方法综合运用（一个句子可能同时使用多种说明方法，要全部找出来）；5.区分说明方法和修辞手法（打比方是说明方法，比喻是修辞手法，在说明文中叫打比方）。",
        "common_mistakes": ["说明方法判断错误（把打比方说成比喻，把作比较说成对比，把举例子说成举例论证）", "作用分析不具体（只说使说明更准确，没有结合具体内容说明说明了什么特征）", "遗漏说明方法（一个句子用了多种说明方法，只找出一种）", "下定义和作诠释混淆（下定义甲和乙可互换，作诠释不能互换）", "说明方法和论证方法混淆（举例子是说明方法，举例论证是论证方法，注意文体）"],
    },
    "文言文": {
        "definition": "文言文是中国古代的书面语言，以先秦口语为基础形成，具有言简意赅、用词精准、句式灵活的特点。文言文阅读是语文学习的重点和难点。",
        "key_points": [
            "文言实词：名词、动词、形容词、数词、量词、代词。重点掌握一词多义、古今异义、通假字、词类活用、偏义复词",
            "文言虚词：18个常见虚词——之、其、而、以、于、为、也、矣、乎、焉、者、所、乃、则、且、若、何、因。重点掌握虚词的多种用法和意义",
            "通假字：本字和通假字读音相同或相近，如说通悦（愉快）、知通智（智慧）、反通返（返回）",
            "古今异义：词义扩大（江：专指长江→泛指江河）、词义缩小（臭：泛指气味→专指臭味）、词义转移（走：跑→行走）、感情色彩变化（卑鄙：地位低微见识浅陋→品质恶劣）",
            "词类活用：名词作动词（沛公军霸上，军：驻军）、名词作状语（箕畚运于渤海之尾，箕畚：用箕畚）、使动用法（项伯杀人，臣活之，活：使……活）、意动用法（渔人甚异之，异：以……为异）、形容词作动词（亲贤臣，远小人，亲/远：亲近/疏远）",
            "文言特殊句式：判断句（……者，……也/乃/则/即/为）、被动句（为……所……/见……于……/被/受）、省略句（省主语/谓语/宾语/介词）、倒装句（宾语前置、定语后置、状语后置、主谓倒装）",
            "文言文翻译方法：留（保留国号年号人名地名官名等）、删（删去无实义的虚词）、补（补出省略成分）、换（换成现代词语）、调（调整倒装句式语序）、变（变通翻译，使符合现代汉语习惯）",
        ],
        "formulas": [
            "文言文翻译口诀：留删补换调变，字字落实要周全；直译为主意译辅，语句通顺是关键",
            "实词推断方法：字形推断法、语境推断法、语法推断法、成语印证法、课文迁移法、邻字帮助法",
            "虚词用法判断：看位置（句首/句中/句尾）、看搭配（与什么词搭配）、看句式（在什么句式中）、看语境（上下文意思）",
            "宾语前置条件：疑问句中疑问代词作宾语前置、否定句中代词作宾语前置、用之或是作标志前置",
        ],
        "examples": [
            "例1（通假字）：学而时习之，不亦说乎？——说通悦，愉快。翻译：学习了知识然后按时温习，不也是很愉快吗？",
            "例2（古今异义）：率妻子邑人来此绝境。——妻子：古义妻子和儿女，今义男子的配偶；绝境：古义与世隔绝的地方，今义没有出路的境地。翻译：带领妻子儿女和同乡人来到这个与世隔绝的地方。",
            "例3（词类活用）：其一犬坐于前。——犬：名词作状语，像狗一样。翻译：其中一只狼像狗一样坐在前面。",
            "例4（使动用法）：春风又绿江南岸。——绿：形容词使动用法，使……变绿。翻译：春风又使江南岸边变绿了。",
            "例5（特殊句式）：何陋之有？——宾语前置，之是标志，正常语序有何陋。翻译：有什么简陋的呢？",
            "例6（翻译）：微斯人，吾谁与归？——微：没有；斯：这；谁与归：与谁归的倒装。翻译：如果没有这种人，我同谁一道呢？",
        ],
        "methods": "文言文学习六步法：1.熟读成诵（多读多背，培养文言语感，积累常见实词虚词和句式）；2.积累字词（建立文言字词积累本，整理通假字、古今异义、一词多义、词类活用）；3.掌握句式（熟悉判断句、被动句、省略句、倒装句四种特殊句式的标志和翻译方法）；4.学会翻译（用留删补换调变六字法，字字落实，直译为主）；5.理解内容（在读懂字词句式基础上理解文章内容、人物形象、思想情感）；6.课外迁移（用课内学到的知识方法阅读课外浅易文言文，举一反三）。建议每天读一篇文言文，持之以恒。",
        "common_mistakes": ["实词只记常用义不记生僻义（一词多义掌握不全）", "虚词用法混淆（之的多种用法分不清，而的连词关系分不清）", "通假字判断错误（把古今字当通假字，或该判断通假的没判断）", "词类活用判断错误（使动和意动混淆，名词作动词和名词作状语混淆）", "翻译不落实（该译的词没译，该补的成分没补，该调的语序没调）", "翻译过于意译（脱离原文，随意发挥，改变原意）", "断句错误（不看虚词标志和句式结构，凭感觉断句）"],
    },
    "古诗": {
        "definition": "古诗是中国古代诗歌的统称，包括古体诗和近体诗（律诗、绝句），具有语言凝练、形象鲜明、意境深远、韵律和谐的特点。学习古诗要理解诗意、体会意境、感受情感、背诵积累。",
        "key_points": [
            "古诗分类：按音律分古体诗（诗经、楚辞、乐府、古风，形式自由，不讲格律）和近体诗（律诗8句、绝句4句，讲究平仄对仗押韵）；按内容分送别诗、思乡诗、边塞诗、山水田园诗、咏物言志诗、怀古咏史诗、闺怨诗、哲理诗等",
            "学习古诗方法：①知作者（了解作者生平、时代背景、创作风格）；②解诗题（理解题目的意思，明确诗歌内容）；③明诗意（理解每个字词的意思，用自己的话说说诗句意思）；④想画面（想象诗歌描绘的画面，进入诗歌意境）；⑤悟情感（体会诗人表达的思想感情）；⑥背诗句（熟读成诵，积累名句）",
            "常见意象：月（思乡怀人）、柳（送别留恋）、菊（隐逸高洁）、梅（坚强高洁）、松（坚贞不屈）、莲（高洁）、雁（思乡传书）、杜鹃（凄哀）、梧桐（凄凉）、夕阳（衰败）、秋风（萧瑟）、春雨（喜悦）",
            "常见情感：思乡怀人、建功报国、怀古伤今、蔑视权贵、愤世嫉俗、怀才不遇、寄情山水、归隐田园、登高览胜、惜春悲秋、送别留恋、哲理思考",
            "表现手法：借景抒情、托物言志、用典、衬托、对比、象征、虚实结合、动静结合、直抒胸臆、情景交融",
            "修辞手法：比喻、拟人、夸张、对偶、排比、反复、反问、设问",
        ],
        "formulas": [
            "古诗学习公式：知作者 + 解诗题 + 明诗意 + 想画面 + 悟情感 + 背诗句",
            "诗意描述公式：时间 + 地点 + 人物 + 景物 + 事件/情感",
            "情感分析公式：意象 + 意境 + 关键词 + 作者背景 → 思想情感",
            "表现手法分析公式：手法 + 具体内容 + 表达效果",
            "炼字分析公式：字义 + 内容 + 手法 + 效果 + 情感",
        ],
        "examples": [
            "例1（思乡诗）：《静夜思》李白——床前明月光，疑是地上霜。举头望明月，低头思故乡。意象：明月；情感：思乡之情；手法：借景抒情。诗意：明亮的月光洒在床前，好像地上结了一层霜。抬头仰望天上的明月，低下头思念远方的故乡。",
            "例2（送别诗）：《送元二使安西》王维——渭城朝雨浥轻尘，客舍青青柳色新。劝君更尽一杯酒，西出阳关无故人。意象：朝雨、柳（送别）、酒；情感：送别留恋、对友人的关切；手法：借景抒情。",
            "例3（边塞诗）：《出塞》王昌龄——秦时明月汉时关，万里长征人未还。但使龙城飞将在，不教胡马度阴山。情感：对边塞将士的同情、对名将的渴望、保家卫国的豪情；手法：用典（龙城飞将指李广）。",
            "例4（山水田园诗）：《春晓》孟浩然——春眠不觉晓，处处闻啼鸟。夜来风雨声，花落知多少。情感：对春天的喜爱、对春光流逝的淡淡惋惜；手法：借景抒情。",
            "例5（哲理诗）：《题西林壁》苏轼——横看成岭侧成峰，远近高低各不同。不识庐山真面目，只缘身在此山中。哲理：要全面客观地看待事物，不能片面；当局者迷，旁观者清。手法：借景说理。",
        ],
        "methods": "古诗学习六步法：1.熟读成诵（多读几遍，读出节奏和韵律，熟读成诵）；2.理解字词（借助注释和工具书理解重点字词的意思，特别是古今异义、词类活用）；3.描述画面（用自己的话描述诗歌描绘的画面，想象诗歌意境）；4.分析意象（找出诗歌中的意象，分析意象的象征意义和表达的情感）；5.体会情感（结合作者背景和诗歌内容，体会诗人表达的思想感情）；6.积累运用（背诵名句，在写作中恰当运用，提高文学素养）。建议每天背一首古诗，持之以恒，积累丰富。",
        "common_mistakes": ["字词理解错误（不看注释，凭现代意思理解古诗字词，如走古义是跑）", "诗意理解表面化（只翻译字面意思，不理解深层含义和意境）", "情感分析错误（不结合作者背景和时代，凭感觉判断情感）", "意象分析错误（不了解常见意象的象征意义，如柳是送别不是春天）", "表现手法判断错误（把借景抒情说成托物言志，把用典说成比喻）", "背诵不熟练（只会背不会写，写错别字，或只会背不会理解运用）"],
    },
    "写人记事": {
        "definition": "写人记事作文是记叙文的一种，以描写人物、叙述事件为主要内容，通过具体事例表现人物性格品质，通过事件叙述表达思想情感。写人记事是小学作文的基础和重点。",
        "key_points": [
            "写人作文要求：①抓住人物特点（外貌、性格、品质、爱好等）；②选取典型事例（用具体事例表现人物特点，一事一品质或多事一品质）；③运用多种描写方法（外貌、语言、动作、心理、神态、细节描写）；④表达真情实感（写出对人物的感情和评价）",
            "记事作文要求：①交代清楚六要素（时间、地点、人物、起因、经过、结果）；②叙事有顺序（顺叙、倒叙、插叙）；③重点突出（经过部分要详写，起因结果略写）；④写出真情实感（在叙事中表达自己的感受和体会）；⑤有中心有意义（事件要说明一个道理或表达一种情感）",
            "写人作文结构：①开头（介绍人物身份外貌，点出人物特点）；②中间（用1-3件具体事例表现人物特点，每件事都要有细节描写）；③结尾（总结人物特点，表达对人物的感情）",
            "记事作文结构：①开头（交代时间地点人物起因，或设置悬念吸引读者）；②经过（详细叙述事件发展过程，注意人物描写和环境描写，写出波澜）；③结尾（交代结果，写出自己的感受和体会，点明中心）",
            "人物描写方法：外貌描写（容貌、衣着、神情、姿态）、语言描写（人物说的话，要符合人物身份性格）、动作描写（人物的行为动作，要准确生动）、心理描写（人物的内心活动，要真实细腻）、神态描写（人物的面部表情）、细节描写（细小的动作、表情、物品等，以小见大）",
        ],
        "formulas": [
            "写人作文公式：人物特点 + 典型事例 + 细节描写 + 真情实感",
            "记事作文公式：六要素 + 叙事顺序 + 详略得当 + 真情实感 + 中心明确",
            "人物描写公式：外貌 + 语言 + 动作 + 心理 + 神态 + 细节",
            "写人开头公式：身份介绍 + 外貌描写 + 特点点题",
            "记事开头公式：设置悬念 / 环境渲染 / 开门见山 / 引用名言",
            "结尾公式：总结特点 + 抒发感情 / 点明中心 + 升华主题 / 照应开头 + 引人深思",
        ],
        "examples": [
            "例1（写人开头）：我的妈妈是一名普通的教师，中等身材，梳着一头利落的短发，脸上总是带着温和的笑容。她是我最敬佩的人，因为她不仅教给我知识，更教会我做人的道理。",
            "例2（人物描写）：他皱紧眉头，眼睛死死地盯着那道数学题，手里的笔在草稿纸上不停地演算着。忽然，他眼睛一亮，猛地一拍桌子：有了！——动作、神态、语言描写，表现他刻苦钻研、豁然开朗的样子。",
            "例3（记事经过）：比赛开始了，我深吸一口气，走上讲台。看着台下几十双眼睛，我的心怦怦直跳，手心都出汗了。我暗暗给自己打气：别怕，你一定行！我开始演讲，声音从一开始的颤抖到后来的坚定，越讲越流畅。——心理、动作描写，写出演讲的紧张和投入。",
            "例4（写人结尾）：这就是我的妈妈，一个平凡而伟大的人。她用自己的言行影响着我，教育着我。我爱我的妈妈，我要做一个像她那样的人。",
            "例5（记事结尾）：通过这件事，我明白了一个道理：做任何事情都不能半途而废，只有坚持到底，才能取得成功。这件事虽然过去了很久，但它一直激励着我前进。",
        ],
        "methods": "写人记事作文写作法：1.认真审题（明确是写人还是记事，写人要抓住特点，记事要写清经过）；2.精心选材（选取最能表现人物特点或中心的典型事例，材料要真实、新颖、有意义）；3.安排结构（开头点题，中间详写，结尾扣题，注意首尾呼应）；4.细致描写（运用多种描写方法，特别是细节描写，让人物形象鲜活，让事件生动）；5.表达真情（写出自己的真实感受，不要假大空，以情动人）；6.认真修改（写完后多读几遍，修改不通顺的地方和错别字）。建议平时多观察生活，积累素材，多写多练。",
        "common_mistakes": ["写人没有特点（人物形象模糊，千人一面，没有写出人物独特之处）", "事例不典型（选取的事例不能表现人物特点，或事例太普通没有意义）", "描写不具体（只有概括叙述，没有细节描写，人物不鲜活，事件不生动）", "记事六要素不全（时间地点人物起因经过结果交代不清楚）", "详略不当（经过部分略写，起因结果详写，重点不突出）", "中心不明确（不知道文章要表达什么，或中心与内容脱节）", "感情不真实（假大空，套话连篇，没有真情实感）"],
    },
}


# 英语知识点详细模板
# ============================================================
# 英语知识点类别详情库
# ============================================================
_ENGLISH_CATEGORY = {
    "时态": {
        "definition": "时态是英语谓语动词通过自身形态变化表示动作发生时间和状态的语法形式。英语共有16种时态，常用的有8种：一般现在时、一般过去时、一般将来时、现在进行时、过去进行时、现在完成时、过去完成时、过去将来时。",
        "key_points": [
            "一般现在时：表示经常发生的动作或存在的状态、客观真理，动词用原形或第三人称单数",
            "一般过去时：表示过去某时间发生的动作或存在的状态，动词用过去式",
            "一般将来时：表示将来某时间要发生的动作或状态，will/shall+动词原形或be going to+动词原形",
            "现在进行时：表示现在正在进行的动作，am/is/are+动词-ing",
            "过去进行时：表示过去某时刻正在进行的动作，was/were+动词-ing",
            "现在完成时：表示过去发生的动作对现在造成的影响或结果，have/has+过去分词",
            "过去完成时：表示过去某时间之前已经完成的动作，had+过去分词",
            "时态呼应：宾语从句中主句是过去时，从句要用相应的过去时态",
        ],
        "formulas": [
            "一般现在时：主语 + 动词原形/三单 + 其他；否定：don't/doesn't + 动词原形；疑问：Do/Does + 主语 + 动词原形？",
            "一般过去时：主语 + 动词过去式 + 其他；否定：didn't + 动词原形；疑问：Did + 主语 + 动词原形？",
            "一般将来时：主语 + will/shall + 动词原形；或 主语 + be going to + 动词原形",
            "现在进行时：主语 + am/is/are + 动词-ing；否定：am/is/are + not + 动词-ing",
            "现在完成时：主语 + have/has + 过去分词；否定：have/has + not + 过去分词",
            "过去完成时：主语 + had + 过去分词；否定：had + not + 过去分词",
            "第三人称单数变化：一般加-s；以s/x/ch/sh/o结尾加-es；辅音字母+y结尾变y为i加-es",
            "动词过去式/过去分词规则变化：一般加-ed；以e结尾加-d；辅音字母+y结尾变y为i加-ed；重读闭音节双写末尾辅音加-ed",
        ],
        "examples": [
            "例1（一般现在时）：She goes to school every day. / The earth goes around the sun.（客观真理）",
            "例2（一般过去时）：I went to the park yesterday. / Did you watch TV last night?",
            "例3（一般将来时）：I will visit my grandma tomorrow. / It is going to rain this afternoon.",
            "例4（现在进行时）：Look! The children are playing football on the playground.",
            "例5（现在完成时）：I have lived in Beijing for ten years. / She has already finished her homework.",
            "例6（过去完成时）：By the end of last year, he had learned 2000 English words.",
        ],
        "methods": "时态学习法：1.理解每种时态的基本概念和用法；2.牢记每种时态的构成形式（肯定句、否定句、疑问句）；3.掌握动词的各种形式变化（三单、过去式、过去分词、现在分词）；4.记住每种时态的时间状语标志词；5.在具体语境中判断和运用时态。做题时先找时间状语，再判断时态。",
        "common_mistakes": ["第三人称单数忘记加-s或-es", "否定句和疑问句中动词没有还原成原形（didn't went→didn't go）", "现在完成时和一般过去时混淆（有明确过去时间状语用一般过去时）", "for和since用法混淆（for+时间段，since+时间点）", "时态呼应错误（主句过去时从句用现在时）", "动词过去式/过去分词变化错误（不规则动词记错）"],
    },
    "从句": {
        "definition": "从句是在复合句中充当某个句子成分的主谓结构，包括宾语从句、定语从句、状语从句等。掌握从句的引导词、语序和时态是重点。",
        "key_points": [
            "宾语从句：在句中作宾语，引导词有that（陈述句）、if/whether（一般疑问句）、疑问词（特殊疑问句），语序用陈述语序",
            "定语从句：修饰名词或代词，先行词是人用who/whom/whose/that，先行词是物用which/that，先行词是时间用when，地点用where，原因用why",
            "状语从句：时间状语从句（when/while/as/before/after/since/until/as soon as）、条件状语从句（if/unless）、原因状语从句（because/since/as）、目的状语从句（so that/in order that）、结果状语从句（so...that/such...that）、让步状语从句（though/although/even if）、比较状语从句（as...as/than）",
            "宾语从句三要素：引导词、语序（陈述语序）、时态（主句现在时从句任意时态；主句过去时从句用相应过去时态；客观真理用一般现在时）",
            "定语从句关系词选择：看先行词是人还是物，看关系词在从句中作什么成分（主语/宾语/状语）",
            "状语从句时态：时间和条件状语从句中，主句将来时从句用一般现在时代替将来时（主将从现）",
        ],
        "formulas": [
            "宾语从句：主句 + 引导词(that/if/whether/疑问词) + 主语 + 谓语（陈述语序）",
            "定语从句：先行词 + 关系代词(who/whom/whose/which/that) + 从句 / 先行词 + 关系副词(when/where/why) + 从句",
            "时间状语从句：when/while/as + 从句，主句",
            "条件状语从句：if/unless + 从句（一般现在时），主句（一般将来时）",
            "原因状语从句：because/since/as + 从句，主句",
            "结果状语从句：so + 形容词/副词 + that + 从句；such + (a/an) + 形容词 + 名词 + that + 从句",
            "让步状语从句：though/although + 从句，主句（不能与but连用）",
        ],
        "examples": [
            "例1（宾语从句）：I think (that) he is right. / I don't know if he will come. / Can you tell me where he lives?（陈述语序，不是where does he live）",
            "例2（定语从句）：The man who is talking to our teacher is my father. / This is the book which I bought yesterday. / I will never forget the day when I joined the army.",
            "例3（时间状语从句）：I was reading when he came in. / While I was watching TV, my mother was cooking.",
            "例4（条件状语从句）：If it rains tomorrow, we will stay at home.（主将从现）/ You will fail unless you work hard.",
            "例5（结果状语从句）：He is so tall that he can reach the top. / It is such an interesting book that I have read it three times.",
            "例6（让步状语从句）：Although he is young, he knows a lot.（不能说Although...but...）",
        ],
        "methods": "从句学习法：1.理解各类从句的基本概念和作用；2.牢记引导词及其用法；3.掌握从句的语序（特别是宾语从句用陈述语序）；4.注意时态呼应（宾语从句时态呼应、状语从句主将从现）；5.在阅读和写作中多练习运用。做题时先判断从句类型，再选引导词，最后检查语序和时态。",
        "common_mistakes": ["宾语从句语序错误（用疑问语序而不是陈述语序）", "宾语从句时态呼应错误（主句过去时从句用现在时）", "定语从句关系词用错（先行词是人用which，或作状语用关系代词）", "if引导宾语从句和条件状语从句混淆（宾语从句中if=是否，时态根据需要；条件状语从句中if=如果，主将从现）", "though/although和but连用（二者不能同时使用）", "so...that和such...that混淆（so后接形容词副词，such后接名词）"],
    },
    "词汇": {
        "definition": "词汇是英语学习的基础，包括单词的音、形、义、用四个方面。掌握词汇的拼写、发音、词义、词性和用法是英语学习的关键。",
        "key_points": [
            "单词记忆方法：音标记忆法、词根词缀法、联想记忆法、分类记忆法、语境记忆法、艾宾浩斯遗忘曲线复习法",
            "词性分类：名词(n.)、动词(v.)、形容词(adj.)、副词(adv.)、代词(pron.)、介词(prep.)、连词(conj.)、冠词(art.)、数词(num.)、感叹词(interj.)",
            "构词法：派生法（加前缀后缀）、合成法（两个词合成一个词）、转化法（一个词转化为另一个词）、缩写和简写",
            "常见前缀：un-/dis-/im-/in-/ir-（否定）、re-（再/重新）、pre-（前/预先）、mis-（错误）、inter-（之间/相互）、trans-（跨越/转移）",
            "常见后缀：-tion/-ment/-ness/-ity（名词）、-ful/-less/-able/-ous/-al（形容词）、-ly（副词）、-ize/-en（动词）",
            "短语搭配：动词短语（look after, give up）、介词短语（in front of, because of）、形容词短语（be good at, be interested in）",
        ],
        "formulas": [
            "名词复数变化：一般加-s；以s/x/ch/sh结尾加-es；辅音字母+y结尾变y为i加-es；以f/fe结尾变f/fe为v加-es；不规则变化（man→men, child→children, sheep→sheep）",
            "形容词副词比较级最高级：一般加-er/-est；以e结尾加-r/-st；辅音字母+y结尾变y为i加-er/-est；重读闭音节双写末尾辅音加-er/-est；多音节前加more/most",
            "动词第三人称单数：一般加-s；以s/x/ch/sh/o结尾加-es；辅音字母+y结尾变y为i加-es",
            "动词现在分词：一般加-ing；以e结尾去e加-ing；重读闭音节双写末尾辅音加-ing",
            "动词过去式/过去分词：规则变化加-ed；不规则变化需单独记忆",
        ],
        "examples": [
            "例1（构词法）：happy→unhappy（否定前缀）、care→careful→carefully（后缀）、class+room=classroom（合成）、water n.水→v.浇水（转化）",
            "例2（名词复数）：book→books, bus→buses, city→cities, leaf→leaves, man→men, child→children, sheep→sheep",
            "例3（比较级最高级）：tall→taller→tallest, nice→nicer→nicest, happy→happier→happiest, big→bigger→biggest, beautiful→more beautiful→most beautiful",
            "例4（短语搭配）：look for（寻找）/look after（照顾）/look up（查阅）/look forward to（期待）；be good at（擅长）/be good for（对...有益）/be good to（对...好）",
            "例5（易混词）：some用于肯定句，any用于否定句和疑问句；few/a few修饰可数名词，little/a little修饰不可数名词；another另一个，other其他的，the other两者中的另一个",
        ],
        "methods": "词汇学习法：1.音形义用结合记忆（不仅记拼写，还要记发音、词义和用法）；2.在语境中记忆（通过句子和文章记单词，不要孤立背单词表）；3.利用构词法扩展词汇（通过词根词缀举一反三）；4.分类整理（按主题、词性、近义词反义词分类）；5.及时复习（根据艾宾浩斯遗忘曲线，在1天、2天、4天、7天、15天后复习）；6.多运用（在听说读写中运用单词）。",
        "common_mistakes": ["单词拼写错误（字母顺序错、漏字母、双写错误）", "词性混淆（把名词当动词用，形容词当副词用）", "近义词辨析不清（spend/cost/take/pay用法混淆）", "短语搭配记错（look for和look after混淆）", "只记中文意思不记用法（不知道单词的搭配和句型）", "背了不复习（很快遗忘）"],
    },
    "语法": {
        "definition": "语法是英语语言的结构规则，包括词法和句法两大部分。词法研究词的形态变化和用法，句法研究句子的结构和类型。掌握语法是正确运用英语的基础。",
        "key_points": [
            "词法：名词（单复数、所有格）、冠词（a/an/the）、代词（人称代词、物主代词、反身代词、不定代词）、数词（基数词、序数词）、介词、连词、形容词副词（比较等级）、动词（时态、语态、非谓语）",
            "句法：句子成分（主语、谓语、宾语、表语、定语、状语、补语）、句子类型（陈述句、疑问句、祈使句、感叹句）、简单句五种基本句型、并列句、复合句",
            "简单句五种基本句型：①主语+谓语(SV)；②主语+谓语+宾语(SVO)；③主语+谓语+间接宾语+直接宾语(SVOO)；④主语+谓语+宾语+宾语补足语(SVOC)；⑤主语+系动词+表语(SVP)",
            "冠词用法：a/an泛指（a用于辅音音素前，an用于元音音素前）；the特指；零冠词用于球类、三餐、学科、交通工具等",
            "被动语态：be+过去分词，各种时态的被动语态（一般现在时am/is/are+done，一般过去时was/were+done，一般将来时will be+done，现在完成时have/has been+done）",
            "非谓语动词：动词不定式(to do)、动名词(doing)、分词(现在分词doing/过去分词done)，在句中作主语、宾语、定语、状语、补语等",
        ],
        "formulas": [
            "被动语态：主语 + be + 过去分词 + (by + 动作执行者)",
            "一般现在时被动：am/is/are + 过去分词",
            "一般过去时被动：was/were + 过去分词",
            "一般将来时被动：will be + 过去分词 / be going to be + 过去分词",
            "现在完成时被动：have/has been + 过去分词",
            "含有情态动词的被动：情态动词 + be + 过去分词",
            "感叹句：What + (a/an) + 形容词 + 名词 + 主语 + 谓语！/ How + 形容词/副词 + 主语 + 谓语！",
            "反意疑问句：陈述句 + 简短疑问句（前肯后否，前否后肯）",
        ],
        "examples": [
            "例1（简单句句型）：He runs. (SV) / He likes apples. (SVO) / He gave me a book. (SVOO) / He made me happy. (SVOC) / He is a teacher. (SVP)",
            "例2（冠词）：I have a cat. The cat is white. / play football（零冠词）/ have lunch（零冠词）",
            "例3（被动语态）：The book was written by Lu Xun. / English is spoken in many countries. / The bridge will be built next year.",
            "例4（非谓语）：I want to go home.（不定式作宾语）/ Swimming is good for health.（动名词作主语）/ The boy standing there is my brother.（现在分词作定语）",
            "例5（感叹句）：What a beautiful girl she is! / How beautiful the girl is!",
            "例6（反意疑问句）：You are a student, aren't you? / He doesn't like English, does he?",
        ],
        "methods": "语法学习法：1.系统学习语法知识（词法+句法，建立语法体系）；2.理解规则而不是死记硬背（知道为什么这样用）；3.在语境中学习语法（通过例句和文章理解语法规则）；4.多做语法练习（巩固所学规则）；5.在写作和口语中运用语法（学以致用）。建议准备一本语法书，遇到问题及时查阅。",
        "common_mistakes": ["冠词用法错误（a/an混用，the漏用或滥用）", "被动语态结构错误（be动词时态错误或过去分词错误）", "非谓语动词形式错误（不定式和动名词混淆，现在分词和过去分词混淆）", "句子结构错误（缺少主语或谓语，双宾语结构错误）", "感叹句what和how混淆", "反意疑问句前后不一致（前肯后肯或前否后否）"],
    },
}


_ENGLISH_DETAIL = {
    "一般现在时": {
        "definition": "一般现在时表示通常性、规律性、习惯性的动作或状态，或者客观真理和事实。",
        "key_points": [
            "表示经常发生的动作或存在的状态，常与always, usually, often, sometimes, every day等时间状语连用",
            "表示客观真理、科学事实、格言等",
            "表示现在的状态、特征、能力等",
            "在时间状语从句和条件状语从句中，用一般现在时代替一般将来时",
            "第三人称单数（he/she/it）作主语时，动词要加-s或-es",
            "be动词根据主语变化：I用am，you/we/they用are，he/she/it用is",
        ],
        "formulas": [
            "肯定句：主语 + 动词原形/动词第三人称单数 + 其他",
            "否定句：主语 + don't/doesn't + 动词原形 + 其他",
            "一般疑问句：Do/Does + 主语 + 动词原形 + 其他？",
            "be动词句型：主语 + am/is/are + 其他；否定：am/is/are + not；疑问：Am/Is/Are + 主语 + 其他？",
            "第三人称单数变化：一般加-s（work→works）；以s/x/ch/sh/o结尾加-es（watch→watches, go→goes）；以辅音字母+y结尾，变y为i加-es（study→studies）",
        ],
        "examples": [
            "肯定句：I go to school every day. / She goes to school every day.",
            "否定句：I don't like coffee. / He doesn't like coffee.",
            "一般疑问句：Do you like English? Yes, I do. / Does she like English? No, she doesn't.",
            "be动词：I am a student. / They are students. / He is a teacher.",
            "客观真理：The earth goes around the sun. / Water boils at 100°C.",
            "时间/条件状语从句：I will call you when I arrive. / If it rains tomorrow, we will stay at home.",
        ],
        "methods": "一般现在时判断法：1.看是否有表示频率的时间状语（always, usually, often, sometimes, every day）；2.看是否是客观真理或事实；3.看是否是现在的状态或习惯；4.看是否是在时间/条件状语从句中。第三人称单数是重点，注意动词变化规则。",
        "common_mistakes": ["第三人称单数忘记加-s或-es", "否定句和疑问句中动词没有还原成原形（doesn't likes→doesn't like）", "be动词和实义动词混用（I am go to school→I go to school）", "时间/条件状语从句中用将来时（when I will arrive→when I arrive）"],
    },
}


def knowledge_detail(stage_subject: str, chapter: str, point: str) -> dict:
    """获取K12知识点的完整教学详情。
    stage_subject: 如 'primary.math', 'junior.chinese', 'senior.english'
    chapter: 章节名称
    point: 知识点名称
    """
    subject = stage_subject.split('.')[-1] if '.' in stage_subject else stage_subject

    # 优先查找详细模板
    if subject == 'math' and point in _MATH_DETAIL:
        return {"point": point, "chapter": chapter, "subject": subject, **_MATH_DETAIL[point]}
    if subject == 'chinese' and point in _CHINESE_DETAIL:
        return {"point": point, "chapter": chapter, "subject": subject, **_CHINESE_DETAIL[point]}
    if subject == 'english' and point in _ENGLISH_DETAIL:
        return {"point": point, "chapter": chapter, "subject": subject, **_ENGLISH_DETAIL[point]}

    # 通用生成：根据学科和知识点关键词生成有实质内容的详情
    detail = _generate_generic_detail(subject, chapter, point)
    return {"point": point, "chapter": chapter, "subject": subject, **detail}


def _generate_generic_detail(subject: str, chapter: str, point: str) -> dict:
    """根据学科和知识点名称生成通用但有实质内容的详情。"""
    if subject == 'math':
        return _generate_math_detail(chapter, point)
    elif subject == 'chinese':
        return _generate_chinese_detail(chapter, point)
    elif subject == 'english':
        return _generate_english_detail(chapter, point)
    elif subject == 'physics':
        return _generate_subject_detail(subject, chapter, point, _PHYSICS_CATEGORY, _PHYSICS_CATEGORY_MAP)
    elif subject == 'chemistry':
        return _generate_subject_detail(subject, chapter, point, _CHEMISTRY_CATEGORY, _CHEMISTRY_CATEGORY_MAP)
    elif subject == 'biology':
        return _generate_subject_detail(subject, chapter, point, _BIOLOGY_CATEGORY, _BIOLOGY_CATEGORY_MAP)
    elif subject == 'history':
        return _generate_subject_detail(subject, chapter, point, _HISTORY_CATEGORY, _HISTORY_CATEGORY_MAP)
    elif subject == 'geography':
        return _generate_subject_detail(subject, chapter, point, _GEOGRAPHY_CATEGORY, _GEOGRAPHY_CATEGORY_MAP)
    elif subject in ('politics', 'morality'):
        return _generate_subject_detail(subject, chapter, point, _POLITICS_CATEGORY, _POLITICS_CATEGORY_MAP)
    else:
        return {
            "definition": f"{point}是{chapter}章节中的重要知识点。",
            "key_points": [f"{point}的基本概念和定义", f"{point}的主要内容和特点", f"{point}的应用场景和方法"],
            "formulas": [],
            "examples": [f"例：{point}的基本应用示例"],
            "methods": f"学习{point}时，要理解基本概念，掌握核心方法，通过练习巩固。",
            "common_mistakes": [f"对{point}的概念理解不透彻", f"应用{point}时忽略关键条件"],
        }


def _generate_math_detail(chapter: str, point: str) -> dict:
    """生成数学知识点详情——根据知识点名称智能匹配类别，生成有针对性的教学内容。"""
    # 类别匹配关键词映射
    category_map = [
        (["数的认识", "整数", "小数", "分数", "百分数", "负数", "数位", "计数单位", "数的改写", "数的大小比较"], "数的认识"),
        (["四则运算", "加法", "减法", "乘法", "除法", "简便运算", "运算定律", "混合运算", "口算", "估算"], "四则运算"),
        (["方程", "解方程", "列方程", "一元一次", "等式", "未知数"], "方程"),
        (["几何", "图形", "周长", "面积", "体积", "表面积", "三角形", "长方形", "正方形", "圆", "圆柱", "圆锥", "平行四边形", "梯形", "长方体", "正方体", "角", "线"], "几何图形"),
        (["应用题", "行程", "工程", "浓度", "利润", "利息", "折扣", "分数应用", "百分数应用", "相遇", "追及"], "应用题"),
        (["比", "比例", "比例尺", "正反比例"], "应用题"),
        (["统计", "平均数", "中位数", "众数", "方差", "标准差", "统计图", "统计表"], "几何图形"),
        (["概率", "可能性", "随机事件"], "应用题"),
        (["函数", "一次函数", "二次函数", "反比例函数", "正比例函数"], "方程"),
        (["三角", "三角函数", "正弦", "余弦", "正切"], "几何图形"),
        (["数列", "等差数列", "等比数列"], "方程"),
        (["导数", "微分", "积分"], "方程"),
        (["向量", "矩阵", "行列式"], "几何图形"),
        (["集合", "逻辑", "命题", "充分条件", "必要条件"], "方程"),
        (["不等式", "一元二次不等式", "绝对值不等式"], "方程"),
    ]

    # 匹配类别
    matched_category = None
    for keywords, cat_name in category_map:
        for kw in keywords:
            if kw in point or kw in chapter:
                matched_category = cat_name
                break
        if matched_category:
            break

    # 如果匹配到类别，使用类别详情
    if matched_category and matched_category in _MATH_CATEGORY:
        cat = _MATH_CATEGORY[matched_category]
        definition = cat["definition"]
        if point not in definition:
            definition = f"【{point}】{definition}"
        return {
            "definition": definition,
            "key_points": cat["key_points"],
            "formulas": cat["formulas"],
            "examples": cat["examples"],
            "methods": cat["methods"],
            "common_mistakes": cat["common_mistakes"],
        }

    # 如果没有匹配到类别，根据知识点类型生成有针对性的内容
    definition = f"{point}是数学{chapter}部分的重要知识点，在数学学习和实际应用中具有重要作用。"

    if any(kw in point for kw in ["定理", "性质", "法则", "公式"]):
        key_points = [
            f"{point}的基本内容和表述",
            f"{point}的条件和结论",
            f"{point}的推导过程和证明思路",
            f"{point}的适用范围和注意事项",
            f"{point}与其他定理公式的联系",
        ]
    elif any(kw in point for kw in ["计算", "运算", "求解"]):
        key_points = [
            f"{point}的基本概念和定义",
            f"{point}的计算方法和步骤",
            f"{point}的常见题型和解题思路",
            f"{point}的简便算法和技巧",
            f"{point}的易错点和注意事项",
        ]
    else:
        key_points = [
            f"{point}的基本概念和定义",
            f"{point}的相关性质和定理",
            f"{point}的计算方法和步骤",
            f"{point}与其他知识点的联系和区别",
            f"{point}在实际问题中的应用",
        ]

    # 根据知识点关键词添加公式
    formulas = []
    if '面积' in point:
        formulas.extend(["长方形面积 = 长 × 宽", "正方形面积 = 边长 × 边长", "三角形面积 = 底 × 高 ÷ 2", "平行四边形面积 = 底 × 高", "梯形面积 = (上底 + 下底) × 高 ÷ 2", "圆的面积 = π × 半径²"])
    if '周长' in point:
        formulas.extend(["长方形周长 = (长 + 宽) × 2", "正方形周长 = 边长 × 4", "圆的周长 = 2 × π × 半径 = π × 直径"])
    if '体积' in point:
        formulas.extend(["长方体体积 = 长 × 宽 × 高", "正方体体积 = 棱长³", "圆柱体积 = 底面积 × 高", "圆锥体积 = 1/3 × 底面积 × 高"])
    if '方程' in point:
        formulas.extend(["等式性质1：等式两边同时加或减同一个数，等式仍成立", "等式性质2：等式两边同时乘或除以同一个不为0的数，等式仍成立", "解方程步骤：去分母→去括号→移项→合并同类项→系数化为1"])
    if '函数' in point:
        formulas.extend(["一次函数：y = kx + b (k≠0)", "正比例函数：y = kx (k≠0)", "反比例函数：y = k/x (k≠0)", "二次函数：y = ax² + bx + c (a≠0)"])
    if '分数' in point:
        formulas.extend(["分数的基本性质：分子分母同时乘或除以同一个不为0的数，分数大小不变", "分数加减法：同分母分母不变分子相加减；异分母先通分再加减", "分数乘法：分子乘分子，分母乘分母", "分数除法：除以一个数等于乘这个数的倒数"])
    if '比' in point or '比例' in point:
        formulas.extend(["比的基本性质：比的前项和后项同时乘或除以同一个不为0的数，比值不变", "比例的基本性质：两内项之积等于两外项之积", "比例尺 = 图上距离 : 实际距离"])
    if '百分数' in point:
        formulas.extend(["百分数 = 比较量 ÷ 标准量 × 100%", "利息 = 本金 × 利率 × 时间", "折扣 = 现价 ÷ 原价", "成活率 = 成活数 ÷ 总数 × 100%"])
    if '角' in point:
        formulas.extend(["1周角 = 360°", "1平角 = 180°", "1直角 = 90°", "锐角 < 90°", "90° < 钝角 < 180°", "三角形内角和 = 180°"])
    if '三角' in point:
        formulas.extend(["sin A = 对边/斜边", "cos A = 邻边/斜边", "tan A = 对边/邻边", "sin²A + cos²A = 1", "正弦定理：a/sin A = b/sin B = c/sin C = 2R", "余弦定理：a² = b² + c² - 2bc cos A"])
    if '数列' in point:
        formulas.extend(["等差数列通项：aₙ = a₁ + (n-1)d", "等差数列求和：Sₙ = n(a₁+aₙ)/2 = na₁ + n(n-1)d/2", "等比数列通项：aₙ = a₁ × q^(n-1)", "等比数列求和：Sₙ = a₁(1-qⁿ)/(1-q) (q≠1)"])
    if '导数' in point:
        formulas.extend(["导数定义：f'(x) = lim(Δx→0) [f(x+Δx)-f(x)]/Δx", "C' = 0 (C为常数)", "(xⁿ)' = nx^(n-1)", "(sin x)' = cos x", "(cos x)' = -sin x", "(eˣ)' = eˣ", "(ln x)' = 1/x"])
    if '概率' in point:
        formulas.extend(["P(A) = 事件A包含的基本事件数 ÷ 基本事件总数", "P(A∪B) = P(A) + P(B) - P(A∩B)", "互斥事件：P(A∪B) = P(A) + P(B)", "对立事件：P(A) + P(Ā) = 1", "独立事件：P(A∩B) = P(A) × P(B)"])
    if '统计' in point:
        formulas.extend(["平均数 = 所有数据之和 ÷ 数据个数", "中位数：数据从小到大排列后中间的数", "众数：出现次数最多的数", "方差 = 各数据与平均数差的平方的平均数", "标准差 = √方差"])

    if not formulas:
        formulas = [f"{point}的相关计算公式和定理", f"应用{point}解决问题的基本关系式"]

    examples = [
        f"例1：{point}的基本概念应用题，直接运用定义和性质求解",
        f"例2：{point}的综合应用题，结合{chapter}中的其他知识点求解",
        f"例3：{point}在实际生活中的应用问题，建立数学模型求解",
    ]

    methods = f"学习{point}的方法：1.理解基本概念和定义；2.掌握相关公式和定理；3.通过例题学习解题步骤；4.多做练习巩固；5.总结常见题型和解题技巧。解题时要认真审题，明确已知条件和所求问题，选择合适的方法。"

    common_mistakes = [
        f"对{point}的概念理解不透彻，定义模糊",
        f"应用{point}的公式时记错公式或忽略适用条件",
        f"计算过程中粗心大意，出现计算错误",
        f"解题时不认真审题，遗漏关键条件或误解题意",
    ]

    return {
        "definition": definition,
        "key_points": key_points,
        "formulas": formulas,
        "examples": examples,
        "methods": methods,
        "common_mistakes": common_mistakes,
    }



def _generate_chinese_detail(chapter: str, point: str) -> dict:
    """生成语文知识点详情——根据知识点名称智能匹配类别，生成有针对性的教学内容。"""
    # 类别匹配关键词映射
    category_map = [
        (["拼音", "音节", "声母", "韵母", "声调", "标调"], "拼音"),
        (["偏旁", "部首", "笔顺", "笔画", "间架", "结构", "形声字", "造字"], "偏旁"),
        (["形近字", "多音字", "多义字", "易错字", "辨析"], "形近字"),
        (["查字典", "音序", "数笔画"], "查字典"),
        (["近义词", "反义词", "同义词", "词语辨析"], "近义词"),
        (["成语", "谚语", "歇后语", "俗语", "格言"], "成语"),
        (["关联词", "关联词语"], "关联词"),
        (["句式转换", "把字句", "被字句", "陈述句", "反问句", "双重否定", "直接引语", "间接引语", "仿写", "扩句", "缩句"], "句式转换"),
        (["病句", "修改病句", "语病"], "病句"),
        (["修辞", "比喻", "拟人", "排比", "夸张", "反问", "设问", "对偶", "反复"], "修辞"),
        (["标点", "标点符号", "引号", "破折号", "省略号", "顿号", "分号", "冒号"], "标点"),
        (["记叙文", "记叙", "六要素", "记叙顺序", "记叙人称", "人物描写", "环境描写", "线索"], "记叙文"),
        (["概括", "段意", "主要内容", "概括段意", "概括主要内容"], "概括"),
        (["中心思想", "中心", "主旨", "主题", "写作目的"], "中心思想"),
        (["说明方法", "说明文", "举例子", "列数字", "作比较", "打比方", "分类别", "下定义"], "说明方法"),
        (["文言文", "文言", "实词", "虚词", "通假字", "古今异义", "词类活用", "特殊句式", "断句", "翻译"], "文言文"),
        (["古诗", "诗词", "诗歌", "唐诗", "宋词", "意象", "意境", "炼字", "名句", "诗词鉴赏", "诗词分类"], "古诗"),
        (["写人", "记事", "写人记事", "记叙文写作", "人物描写", "细节描写"], "写人记事"),
        (["写景", "状物", "写景状物"], "写人记事"),
        (["应用文", "书信", "通知", "日记", "请假条", "倡议书"], "写人记事"),
        (["看图写话", "看图作文"], "写人记事"),
        (["审题", "选材", "立意", "构思", "作文审题", "材料作文", "任务驱动"], "写人记事"),
        (["开头", "结尾", "过渡", "照应", "开头结尾"], "写人记事"),
        (["修改作文", "作文修改", "升格"], "写人记事"),
        (["想象作文", "想象"], "写人记事"),
        (["读后感", "观后感", "读书笔记"], "写人记事"),
        (["散文", "散文阅读", "散文主旨", "散文线索", "散文语言", "散文情感"], "记叙文"),
        (["小说", "小说阅读", "小说三要素", "人物形象", "情节", "环境"], "记叙文"),
        (["议论文", "议论文阅读", "论证方法", "论点", "论据", "论证思路"], "说明方法"),
        (["非连续性文本", "图文转换", "图表"], "说明方法"),
        (["句段作用", "段落作用", "句子赏析", "词语赏析", "标题含义", "关键句"], "记叙文"),
        (["表现手法", "表达方式", "象征", "对比", "衬托", "铺垫", "伏笔", "悬念", "抑扬", "托物言志", "借景抒情"], "记叙文"),
        (["名著", "名著导读", "文学常识", "作家作品", "文化常识", "文体知识"], "古诗"),
        (["字音", "字形", "易错字音", "字音字形", "汉字"], "偏旁"),
        (["词语", "词语运用", "词语搭配", "词语归类", "词语感情色彩", "量词", "叠词", "实词", "虚词"], "近义词"),
        (["语法", "词性", "短语", "单句", "复句", "复句类型"], "关联词"),
        (["语言连贯", "语言得体", "语言简明", "语言运用", "连贯", "得体"], "关联词"),
        (["扩展语句", "压缩语段", "选用仿用变换句式"], "句式转换"),
        (["论述类文本", "实用类文本", "文学类文本", "现代文阅读"], "记叙文"),
        (["名篇名句", "默写", "必背篇目", "理解性默写", "情境式默写", "易错字"], "古诗"),
        (["写作", "作文", "议论文写作", "分论点", "论据", "论证", "结构模板", "素材", "卷面"], "写人记事"),
    ]

    # 匹配类别
    matched_category = None
    for keywords, cat_name in category_map:
        for kw in keywords:
            if kw in point or kw in chapter:
                matched_category = cat_name
                break
        if matched_category:
            break

    # 如果匹配到类别，使用类别详情
    if matched_category and matched_category in _CHINESE_CATEGORY:
        cat = _CHINESE_CATEGORY[matched_category]
        # 在类别详情基础上，结合具体知识点名称做微调
        definition = cat["definition"]
        if point not in definition:
            definition = f"【{point}】{definition}"
        return {
            "definition": definition,
            "key_points": cat["key_points"],
            "formulas": cat["formulas"],
            "examples": cat["examples"],
            "methods": cat["methods"],
            "common_mistakes": cat["common_mistakes"],
        }

    # 如果没有匹配到类别，根据知识点名称生成有针对性的内容
    # 不再使用通用模板，而是根据知识点名称中的关键词生成内容
    definition = f"{point}是语文{chapter}部分的重要知识点。"

    # 根据知识点类型生成不同的要点
    if any(kw in point for kw in ["方法", "技巧", "策略", "途径", "方式"]):
        key_points = [
            f"{point}的基本概念和适用范围",
            f"{point}的具体操作步骤和实施方法",
            f"{point}的常见类型和分类",
            f"{point}在阅读和写作中的实际应用",
            f"{point}的注意事项和常见问题",
        ]
        formulas = [
            f"{point}的操作流程：准备→实施→检查→总结",
            f"{point}的评价标准：准确性+完整性+规范性+创新性",
        ]
    elif any(kw in point for kw in ["类型", "种类", "分类", "类别"]):
        key_points = [
            f"{point}的基本概念和定义",
            f"{point}的分类标准和划分依据",
            f"{point}的各类别特点和区别",
            f"{point}各类别的典型例子和应用场景",
            f"{point}的辨析方法和判断技巧",
        ]
        formulas = [
            f"{point}分类公式：分类标准 + 各类别特征 + 典型例子",
            f"{point}辨析公式：定义 + 特征 + 例子 + 区别",
        ]
    elif any(kw in point for kw in ["作用", "效果", "意义", "影响", "功能", "价值"]):
        key_points = [
            f"{point}的基本概念和内涵",
            f"{point}在内容方面的作用和效果",
            f"{point}在结构方面的作用和效果",
            f"{point}在表达情感方面的作用",
            f"{point}的典型例子和分析方法",
        ]
        formulas = [
            f"{point}作用分析公式：内容作用 + 结构作用 + 情感作用",
            f"{point}效果分析公式：手法 + 内容 + 效果 + 情感",
        ]
    elif any(kw in point for kw in ["分析", "鉴赏", "赏析", "评价", "解读"]):
        key_points = [
            f"{point}的基本概念和分析对象",
            f"{point}的分析角度和维度",
            f"{point}的分析方法和步骤",
            f"{point}的答题思路和规范",
            f"{point}的典型例题和答案解析",
        ]
        formulas = [
            f"{point}分析公式：手法/角度 + 具体内容 + 表达效果 + 思想情感",
            f"{point}答题公式：观点 + 分析 + 总结",
        ]
    else:
        # 通用但有针对性的要点
        key_points = [
            f"{point}的基本概念和定义",
            f"{point}的主要特点和表现形式",
            f"{point}的分类和类型",
            f"{point}在阅读和写作中的应用",
            f"{point}的常见考查方式和答题技巧",
        ]
        formulas = [
            f"{point}的知识体系：概念 + 特点 + 分类 + 应用 + 技巧",
            f"{point}的学习方法：理解概念 + 积累例子 + 练习运用 + 总结规律",
        ]

    examples = [
        f"例1：{point}的基本概念辨析，结合具体例子理解",
        f"例2：{point}在阅读理解中的应用，结合文本分析",
        f"例3：{point}在写作中的运用，写出具体片段",
    ]

    methods = f"学习{point}的方法：1.理解基本概念，建立知识体系；2.结合具体例子学习，避免死记硬背；3.在阅读中体会和运用；4.在写作中实践和巩固；5.总结常见题型和答题模板。答题时要结合具体语境，不能脱离文本空谈概念。"

    common_mistakes = [
        f"对{point}的概念理解表面化，不能深入本质",
        f"在阅读分析中生搬硬套概念，不能结合具体文本",
        f"在写作中运用不自然，为了用而用",
        f"答题时要点不全，遗漏重要得分点",
    ]

    return {
        "definition": definition,
        "key_points": key_points,
        "formulas": formulas,
        "examples": examples,
        "methods": methods,
        "common_mistakes": common_mistakes,
    }



def _generate_english_detail(chapter: str, point: str) -> dict:
    """生成英语知识点详情——根据知识点名称智能匹配类别，生成有针对性的教学内容。"""
    # 类别匹配关键词映射
    category_map = [
        (["时态", "一般现在", "一般过去", "一般将来", "现在进行", "过去进行", "现在完成", "过去完成", "过去将来"], "时态"),
        (["从句", "宾语从句", "定语从句", "状语从句", "名词性从句", "主语从句", "表语从句", "同位语从句"], "从句"),
        (["词汇", "单词", "短语", "词组", "构词法", "词根", "词缀", "名词复数", "比较级", "最高级"], "词汇"),
        (["语法", "冠词", "代词", "介词", "连词", "数词", "被动语态", "非谓语", "虚拟语气", "主谓一致", "倒装", "强调", "句子成分", "简单句", "并列句", "复合句", "感叹句", "反意疑问句", "祈使句"], "语法"),
        (["听力", "口语", "阅读", "写作", "翻译", "完形填空", "阅读理解", "书面表达"], "语法"),
        (["语音", "音标", "发音", "重音", "语调", "连读"], "词汇"),
    ]

    # 匹配类别
    matched_category = None
    for keywords, cat_name in category_map:
        for kw in keywords:
            if kw in point or kw in chapter:
                matched_category = cat_name
                break
        if matched_category:
            break

    # 如果匹配到类别，使用类别详情
    if matched_category and matched_category in _ENGLISH_CATEGORY:
        cat = _ENGLISH_CATEGORY[matched_category]
        definition = cat["definition"]
        if point not in definition:
            definition = f"【{point}】{definition}"
        return {
            "definition": definition,
            "key_points": cat["key_points"],
            "formulas": cat["formulas"],
            "examples": cat["examples"],
            "methods": cat["methods"],
            "common_mistakes": cat["common_mistakes"],
        }

    # 如果没有匹配到类别，根据知识点类型生成有针对性的内容
    definition = f"{point}是英语{chapter}部分的重要语法点或知识点，是英语学习的基础和重点。"

    if any(kw in point for kw in ["时态", "语态"]):
        key_points = [
            f"{point}的基本概念和用法",
            f"{point}的构成形式（肯定句、否定句、疑问句）",
            f"{point}的时间状语标志词",
            f"{point}与其他时态/语态的区别",
            f"{point}的常见考点和易错点",
        ]
    elif any(kw in point for kw in ["从句", "句子"]):
        key_points = [
            f"{point}的基本概念和分类",
            f"{point}的引导词及其用法",
            f"{point}的语序和时态要求",
            f"{point}的常见句型和例句",
            f"{point}的易错点和注意事项",
        ]
    else:
        key_points = [
            f"{point}的基本概念和定义",
            f"{point}的构成形式和变化规则",
            f"{point}的用法和适用场景",
            f"{point}的肯定句、否定句、疑问句形式",
            f"{point}的常见考点和易错点",
        ]

    formulas = []
    if '时态' in point:
        formulas = [
            "一般现在时：主语 + 动词原形/三单 + 其他",
            "一般过去时：主语 + 动词过去式 + 其他",
            "一般将来时：主语 + will/shall + 动词原形 / be going to + 动词原形",
            "现在进行时：主语 + am/is/are + 动词-ing",
            "过去进行时：主语 + was/were + 动词-ing",
            "现在完成时：主语 + have/has + 动词过去分词",
            "过去完成时：主语 + had + 动词过去分词",
        ]
    if '从句' in point:
        formulas = [
            "宾语从句：主句 + 引导词(that/if/whether/疑问词) + 主语 + 谓语",
            "定语从句：先行词 + 关系代词(who/whom/whose/which/that) + 从句 / 先行词 + 关系副词(when/where/why) + 从句",
            "状语从句：时间(when/while/as/before/after/since/until/as soon as)、条件(if/unless)、原因(because/since/as)、目的(so that/in order that)、结果(so...that/such...that)、让步(though/although/even if)、比较(as...as/than)",
        ]
    if '被动' in point:
        formulas = [
            "被动语态基本结构：主语 + be + 过去分词 + (by + 执行者)",
            "一般现在时被动：am/is/are + 过去分词",
            "一般过去时被动：was/were + 过去分词",
            "一般将来时被动：will be + 过去分词",
            "现在完成时被动：have/has been + 过去分词",
            "含情态动词被动：情态动词 + be + 过去分词",
        ]
    if '非谓语' in point:
        formulas = [
            "动词不定式：to + 动词原形（作主语、宾语、定语、状语、补语）",
            "动名词：动词-ing（作主语、宾语、表语、定语）",
            "现在分词：动词-ing（作定语、状语、补语、表语，表主动进行）",
            "过去分词：动词-ed（作定语、状语、补语、表语，表被动完成）",
        ]
    if '冠词' in point:
        formulas = [
            "不定冠词a/an：泛指，a用于辅音音素前，an用于元音音素前",
            "定冠词the：特指，双方都知道的人或物、上文提到过的、世界上独一无二的",
            "零冠词：球类运动、三餐、学科、交通工具、节日、星期月份季节",
        ]
    if '比较' in point or '最高级' in point:
        formulas = [
            "比较级：形容词/副词 + er（或more + 原级），常与than连用",
            "最高级：the + 形容词/副词 + est（或most + 原级），常与in/of范围连用",
            "as...as：和...一样（原级比较），not as/so...as：不如...",
            "比较级+and+比较级：越来越...",
            "the+比较级，the+比较级：越...越...",
        ]

    if not formulas:
        formulas = [f"{point}的基本构成形式和规则", f"应用{point}的常见句型和搭配"]

    examples = [
        f"例1：{point}的基本用法，肯定句/否定句/疑问句转换",
        f"例2：{point}在具体语境中的运用，结合上下文判断",
        f"例3：{point}的常见考题，选择正确形式填空",
    ]

    methods = f"学习{point}的方法：1.理解基本概念和规则；2.牢记构成形式和变化规则；3.通过例句学习用法；4.多做练习巩固；5.在阅读和写作中运用。做题时要结合具体语境，注意时间状语和上下文提示。"

    common_mistakes = [
        f"对{point}的规则理解不透彻，形式记错",
        f"应用{point}时忽略适用条件和特殊情况",
        f"在具体语境中判断错误，没有结合上下文",
        f"写作中运用不自然或出现语法错误",
    ]

    return {
        "definition": definition,
        "key_points": key_points,
        "formulas": formulas,
        "examples": examples,
        "methods": methods,
        "common_mistakes": common_mistakes,
    }




# ============================================================
# 物理知识点类别详情库
# ============================================================
_PHYSICS_CATEGORY = {
    "力学": {
        "definition": "力学是物理学的基础分支，研究物体的运动规律和力的作用。包括运动学、动力学、功和能、动量、机械振动和波等内容。",
        "key_points": [
            "运动学：描述物体运动的规律，包括匀速直线运动、匀变速直线运动、自由落体运动、抛体运动、圆周运动",
            "牛顿运动定律：牛顿第一定律（惯性定律）、牛顿第二定律（F=ma）、牛顿第三定律（作用力与反作用力）",
            "力的分类：重力（G=mg）、弹力（胡克定律F=kx）、摩擦力（滑动摩擦f=μN，静摩擦）、万有引力",
            "功和能：功W=Fs cosθ，功率P=W/t=Fv，动能定理，机械能守恒定律",
            "动量：动量p=mv，冲量I=Ft，动量守恒定律，碰撞问题",
            "机械振动和波：简谐运动、单摆、波的传播、波的干涉和衍射",
        ],
        "formulas": [
            "匀速直线运动：v = s/t，s = vt",
            "匀变速直线运动：v = v₀ + at，s = v₀t + ½at²，v² - v₀² = 2as",
            "自由落体：v = gt，h = ½gt²，v² = 2gh",
            "牛顿第二定律：F = ma",
            "重力：G = mg（g≈9.8m/s²）",
            "滑动摩擦力：f = μN",
            "功：W = Fs cosθ",
            "功率：P = W/t = Fv",
            "动能：Eₖ = ½mv²",
            "重力势能：Eₚ = mgh",
            "动能定理：W合 = ΔEₖ = ½mv² - ½mv₀²",
            "机械能守恒：Eₖ₁ + Eₚ₁ = Eₖ₂ + Eₚ₂",
            "动量：p = mv",
            "动量守恒：m₁v₁ + m₂v₂ = m₁v₁' + m₂v₂'",
        ],
        "examples": [
            "例1：一物体从静止开始做匀加速直线运动，加速度2m/s²，求5秒后的速度和位移。解：v=at=2×5=10m/s，s=½at²=½×2×25=25m",
            "例2：质量2kg的物体在水平面上受到10N的水平拉力，摩擦力4N，求加速度。解：F合=10-4=6N，a=F/m=6/2=3m/s²",
            "例3：质量1kg的物体从10m高处自由下落，求落地时速度。解：v²=2gh=2×10×10=200，v=10√2≈14.1m/s（或用机械能守恒mgh=½mv²）",
            "例4：质量2kg的物体以3m/s速度运动，与质量1kg静止的物体发生完全非弹性碰撞，求共同速度。解：2×3=(2+1)v，v=2m/s",
        ],
        "methods": "力学学习法：1.理解基本概念（位移、速度、加速度、力、功、能、动量）；2.掌握基本公式和定律（牛顿定律、动能定理、机械能守恒、动量守恒）；3.学会受力分析（画受力图，分析重力、弹力、摩擦力）；4.选择合适的规律解题（动力学问题用牛顿定律，过程问题用动能定理或动量守恒）；5.多做练习，总结解题方法。",
        "common_mistakes": ["受力分析错误（漏力或多力，摩擦力方向判断错误）", "公式适用条件错误（机械能守恒条件、动量守恒条件判断错误）", "矢量方向错误（速度、加速度、力、动量是矢量，要注意方向）", "单位不统一（计算时没有换算成国际单位）", "运动学公式记错（位移公式和速度公式混淆）"],
    },
    "电磁学": {
        "definition": "电磁学是物理学的重要分支，研究电现象、磁现象及其相互关系。包括静电场、恒定电流、磁场、电磁感应、交变电流等内容。",
        "key_points": [
            "静电场：电荷守恒定律、库仑定律、电场强度、电势、电势能、电容器",
            "恒定电流：欧姆定律、电阻定律、串并联电路、电功和电功率、闭合电路欧姆定律",
            "磁场：磁场的基本性质、磁感应强度、安培力、洛伦兹力、带电粒子在磁场中的运动",
            "电磁感应：电磁感应现象、楞次定律、法拉第电磁感应定律、自感和互感",
            "交变电流：交变电流的产生、描述交变电流的物理量、变压器、远距离输电",
        ],
        "formulas": [
            "库仑定律：F = kq₁q₂/r²（k=9×10⁹N·m²/C²）",
            "电场强度：E = F/q，点电荷电场E = kQ/r²",
            "电势差：U = W/q，匀强电场U = Ed",
            "电容：C = Q/U，平行板电容器C = εS/(4πkd)",
            "欧姆定律：I = U/R",
            "电阻定律：R = ρL/S",
            "电功：W = UIt，电功率：P = UI = I²R = U²/R",
            "闭合电路欧姆定律：I = E/(R+r)，路端电压U = E - Ir",
            "安培力：F = BIL（B⊥I）",
            "洛伦兹力：f = qvB（v⊥B）",
            "带电粒子圆周运动：qvB = mv²/r，r = mv/(qB)，T = 2πm/(qB)",
            "法拉第电磁感应定律：E = nΔΦ/Δt，导体切割E = BLv",
            "变压器：U₁/U₂ = n₁/n₂，P₁ = P₂（理想变压器）",
        ],
        "examples": [
            "例1：两个点电荷q₁=2×10⁻⁶C，q₂=3×10⁻⁶C，相距0.3m，求相互作用力。解：F=kq₁q₂/r²=9×10⁹×2×10⁻⁶×3×10⁻⁶/0.09=0.6N",
            "例2：电阻R=10Ω，两端电压U=5V，求电流和功率。解：I=U/R=5/10=0.5A，P=UI=5×0.5=2.5W",
            "例3：导体棒长L=0.5m，在B=0.2T的匀强磁场中以v=4m/s垂直切割磁感线，求感应电动势。解：E=BLv=0.2×0.5×4=0.4V",
            "例4：电子以v=2×10⁶m/s垂直进入B=0.001T的磁场，求圆周运动半径。解：r=mv/(eB)=9.1×10⁻³¹×2×10⁶/(1.6×10⁻¹⁹×0.001)≈0.0114m",
        ],
        "methods": "电磁学学习法：1.理解基本概念（电场、磁场、电势、电流、电动势）；2.掌握基本公式和定律（库仑定律、欧姆定律、安培力、洛伦兹力、法拉第电磁感应定律）；3.学会画电路图和受力图（电路分析和带电粒子受力分析）；4.理解物理过程（电磁感应中磁通量变化、楞次定律判断方向）；5.多做实验和练习，理论联系实际。",
        "common_mistakes": ["电场强度和电势混淆（E是矢量，φ是标量）", "安培力和洛伦兹力方向判断错误（左手定则）", "楞次定律应用错误（感应电流方向判断）", "电路分析错误（串并联判断错误，短路断路识别错误）", "变压器公式用错（电压比等于匝数比，电流比等于匝数反比）"],
    },
}

# ============================================================
# 化学知识点类别详情库
# ============================================================
_CHEMISTRY_CATEGORY = {
    "物质结构": {
        "definition": "物质结构是化学的基础理论，研究原子结构、分子结构和晶体结构，揭示物质的性质与结构的关系。包括原子结构、元素周期律、化学键、分子间作用力等内容。",
        "key_points": [
            "原子结构：原子由原子核（质子+中子）和核外电子组成，质子数=原子序数=核外电子数，质量数=质子数+中子数",
            "核外电子排布：电子层（K/L/M/N...），每层最多容纳2n²个电子，最外层不超过8个，次外层不超过18个",
            "元素周期律：元素的性质随原子序数递增呈周期性变化，包括原子半径、金属性非金属性、化合价、最高价氧化物水化物酸碱性",
            "元素周期表：7个周期（短周期1-3，长周期4-6，不完全周期7），16个族（7主族7副族+Ⅷ族+0族）",
            "化学键：离子键（阴阳离子间静电作用，活泼金属+活泼非金属）、共价键（原子间共用电子对，非金属之间）、金属键（金属阳离子与自由电子）",
            "分子间作用力：范德华力（影响熔沸点，相对分子质量越大范德华力越大）、氢键（N/O/F与H形成，使熔沸点异常升高）",
        ],
        "formulas": [
            "原子组成：质子数(Z) + 中子数(N) = 质量数(A)",
            "核外电子排布：第n层最多容纳2n²个电子",
            "同周期元素性质递变：从左到右原子半径减小，金属性减弱，非金属性增强",
            "同主族元素性质递变：从上到下原子半径增大，金属性增强，非金属性减弱",
            "离子键形成：活泼金属（IA、IIA）+ 活泼非金属（VIA、VIIA）",
            "共价键类型：极性共价键（不同原子）、非极性共价键（相同原子）",
        ],
        "examples": [
            "例1：钠原子（原子序数11）的核外电子排布：2,8,1，最外层1个电子，容易失去形成Na⁺",
            "例2：氯原子（原子序数17）的核外电子排布：2,8,7，最外层7个电子，容易得到1个电子形成Cl⁻",
            "例3：NaCl的形成：Na失去1个电子给Cl，形成Na⁺和Cl⁻，通过离子键结合成离子化合物",
            "例4：HCl的形成：H和Cl各提供1个电子形成共用电子对，通过共价键结合成共价化合物",
            "例5：第三周期元素Na、Mg、Al、Si、P、S、Cl，从左到右金属性减弱，非金属性增强，最高价氧化物水化物从NaOH（强碱）到HClO₄（强酸）",
        ],
        "methods": "物质结构学习法：1.理解原子结构和核外电子排布规律；2.掌握元素周期律和周期表结构（记住周期和族的划分）；3.理解化学键类型和形成条件（离子键、共价键、金属键）；4.学会用结构解释性质（如熔沸点高低、稳定性、酸碱性）；5.多做推断题练习，熟练运用周期律。",
        "common_mistakes": ["原子结构中质量数和相对原子质量混淆", "核外电子排布错误（最外层超过8个，或次外层超过18个）", "离子键和共价键判断错误（AlCl₃是共价化合物不是离子化合物）", "元素周期律递变规律记错（同周期同主族性质递变方向混淆）", "氢键和范德华力混淆（氢键只存在于含N/O/F与H的分子间）"],
    },
    "化学反应": {
        "definition": "化学反应是化学研究的核心，研究化学反应的本质、类型、速率和限度。包括氧化还原反应、离子反应、化学反应速率、化学平衡、电解质溶液等内容。",
        "key_points": [
            "氧化还原反应：有电子转移（化合价升降）的反应，氧化剂得电子化合价降低被还原，还原剂失电子化合价升高被氧化",
            "离子反应：有离子参加的反应，用离子方程式表示，书写步骤：写化学方程式→拆（易溶易电离的拆成离子）→删（删去两边相同的离子）→查（电荷守恒、原子守恒）",
            "化学反应速率：单位时间内反应物浓度的减少或生成物浓度的增加，v=Δc/Δt，影响因素：浓度、温度、压强、催化剂、接触面积",
            "化学平衡：在一定条件下的可逆反应，正反应速率等于逆反应速率，各组分浓度保持不变的状态",
            "勒夏特列原理：如果改变影响平衡的一个条件（浓度、温度、压强），平衡就向能够减弱这种改变的方向移动",
            "电解质溶液：强电解质（强酸、强碱、大部分盐，完全电离）、弱电解质（弱酸、弱碱、水，部分电离），水的离子积Kw=c(H⁺)·c(OH⁻)=1×10⁻¹⁴",
        ],
        "formulas": [
            "化学反应速率：v = Δc/Δt，单位mol/(L·s)或mol/(L·min)",
            "速率比等于化学计量数比：v(A):v(B):v(C) = a:b:c",
            "平衡常数：对于aA+bB⇌cC+dD，K = [C]^c[D]^d/[A]^a[B]^b",
            "pH = -lg c(H⁺)，pOH = -lg c(OH⁻)，pH + pOH = 14（常温）",
            "中和滴定：c(酸)V(酸) = c(碱)V(碱)（一元酸碱）",
            "氧化还原反应电子守恒：氧化剂得电子总数 = 还原剂失电子总数",
        ],
        "examples": [
            "例1（氧化还原）：2Na + Cl₂ = 2NaCl，Na是还原剂（化合价0→+1，失电子），Cl₂是氧化剂（化合价0→-1，得电子）",
            "例2（离子方程式）：盐酸与氢氧化钠反应：H⁺ + OH⁻ = H₂O（写：HCl+NaOH=NaCl+H₂O，拆：H⁺+Cl⁻+Na⁺+OH⁻=Na⁺+Cl⁻+H₂O，删：H⁺+OH⁻=H₂O）",
            "例3（反应速率）：某反应2min内反应物浓度从2mol/L降到0.5mol/L，v=(2-0.5)/2=0.75mol/(L·min)",
            "例4（化学平衡移动）：对于N₂+3H₂⇌2NH₃（正反应放热），增大压强平衡正向移动，升高温度平衡逆向移动",
            "例5（pH计算）：0.01mol/L盐酸的pH=-lg(0.01)=2；0.01mol/L NaOH的pOH=2，pH=14-2=12",
        ],
        "methods": "化学反应学习法：1.理解氧化还原反应的本质（电子转移），学会判断氧化剂还原剂和配平；2.掌握离子方程式书写方法（写拆删查四步法）；3.理解反应速率的概念和影响因素；4.掌握化学平衡的特征和勒夏特列原理，学会判断平衡移动方向；5.理解电解质电离和pH计算。多做计算题和平衡移动分析题。",
        "common_mistakes": ["氧化还原反应中氧化剂还原剂判断错误（化合价升降方向搞反）", "离子方程式书写错误（该拆的不拆，不该拆的拆了，如弱酸弱碱不能拆）", "反应速率计算错误（单位换算错误，或用物质的量变化代替浓度变化）", "化学平衡移动方向判断错误（没有正确应用勒夏特列原理）", "pH计算错误（弱酸弱碱不能直接用浓度计算pH，要考虑电离度）"],
    },
}

# ============================================================
# 生物知识点类别详情库
# ============================================================
_BIOLOGY_CATEGORY = {
    "细胞": {
        "definition": "细胞是生物体结构和功能的基本单位。细胞生物学研究细胞的结构、功能、生命活动规律，包括细胞的分子组成、结构、物质输入输出、能量供应、细胞增殖分化衰老凋亡等内容。",
        "key_points": [
            "细胞的分子组成：大量元素（C/H/O/N/P/S/K/Ca/Mg）、微量元素（Fe/Mn/Zn/Cu/B/Mo），最基本元素C，基本元素C/H/O/N",
            "化合物：无机物（水、无机盐）、有机物（糖类、脂质、蛋白质、核酸）",
            "蛋白质：基本单位氨基酸（约20种），结构多样性原因（氨基酸种类、数目、排列顺序、肽链空间结构），功能（催化、运输、调节、免疫、结构）",
            "核酸：DNA（脱氧核糖核酸，双螺旋结构，主要在细胞核）、RNA（核糖核酸，主要在细胞质），基本单位核苷酸",
            "细胞结构：原核细胞（无核膜包被的细胞核，如细菌、蓝藻）、真核细胞（有核膜包被的细胞核，如动物、植物、真菌）",
            "细胞器：线粒体（有氧呼吸主要场所）、叶绿体（光合作用场所）、内质网（蛋白质合成加工）、高尔基体（蛋白质加工分泌）、核糖体（蛋白质合成场所）、溶酶体（消化车间）、液泡（植物细胞）、中心体（动物和低等植物）",
            "细胞膜：流动镶嵌模型，主要成分磷脂和蛋白质，功能特点选择透过性，结构特点流动性",
        ],
        "formulas": [
            "氨基酸结构通式：H₂N-CH(R)-COOH，至少有一个氨基和一个羧基连在同一个碳原子上",
            "肽键数 = 氨基酸数 - 肽链数",
            "蛋白质分子量 = 氨基酸平均分子量 × 氨基酸数 - 18 × 脱去水分子数",
            "DNA结构：双螺旋，碱基互补配对A-T（2个氢键）、G-C（3个氢键）",
            "有氧呼吸总反应式：C₆H₁₂O₆ + 6O₂ + 6H₂O → 6CO₂ + 12H₂O + 能量",
            "光合作用总反应式：6CO₂ + 12H₂O → C₆H₁₂O₆ + 6O₂ + 6H₂O（光能、叶绿体）",
            "有丝分裂染色体数变化：间期2N→前期2N→中期2N→后期4N→末期2N",
        ],
        "examples": [
            "例1：100个氨基酸形成2条肽链，肽键数=100-2=98个，脱去98分子水",
            "例2：DNA分子中A有30个，占20%，则总碱基数=30/20%=150个，T=A=30个，G=C=(150-60)/2=45个",
            "例3：有氧呼吸三个阶段：第一阶段细胞质基质（葡萄糖→丙酮酸+[H]+少量能量），第二阶段线粒体基质（丙酮酸+H₂O→CO₂+[H]+少量能量），第三阶段线粒体内膜（[H]+O₂→H₂O+大量能量）",
            "例4：光合作用光反应（类囊体薄膜）：水的光解产生O₂和[H]，合成ATP；暗反应（叶绿体基质）：CO₂固定和C₃还原，消耗ATP和[H]，生成有机物",
            "例5：植物细胞特有的结构：细胞壁、叶绿体、液泡；动物细胞和低等植物细胞有中心体",
        ],
        "methods": "细胞生物学学习法：1.理解细胞的分子组成（元素和化合物，特别是蛋白质和核酸的结构功能）；2.掌握细胞结构和各细胞器功能（对比记忆动植物细胞、原核真核细胞的区别）；3.理解细胞代谢（光合作用和呼吸作用的过程、场所、物质能量变化）；4.掌握细胞增殖（有丝分裂各时期特点和染色体DNA变化）；5.多画细胞结构图和代谢过程图，帮助理解记忆。",
        "common_mistakes": ["原核细胞和真核细胞混淆（原核细胞只有核糖体一种细胞器，没有核膜）", "细胞器功能记错（线粒体和叶绿体功能混淆，内质网和高尔基体功能混淆）", "氨基酸脱水缩合计算错误（肽键数=氨基酸数-肽链数，不是氨基酸数-1）", "光合作用和呼吸作用过程混淆（光反应暗反应场所和物质变化记错）", "有丝分裂各时期特点记错（前期、中期、后期、末期的染色体行为和数目变化）"],
    },
}

# ============================================================
# 历史知识点类别详情库
# ============================================================
_HISTORY_CATEGORY = {
    "中国古代史": {
        "definition": "中国古代史从远古时期到1840年鸦片战争前，包括原始社会、奴隶社会（夏商周）、封建社会（秦汉至明清）三个阶段，研究中国古代政治制度、经济发展、文化成就、民族关系和对外交往。",
        "key_points": [
            "先秦时期：夏（第一个奴隶制王朝）、商（甲骨文、青铜器）、西周（分封制、宗法制、井田制）、春秋战国（百家争鸣、铁犁牛耕、商鞅变法）",
            "秦汉时期：秦统一六国（中央集权制度：皇帝制、三公九卿、郡县制）、汉武帝大一统（推恩令、罢黜百家独尊儒术、盐铁官营）",
            "魏晋南北朝：政权分立、民族融合（北魏孝文帝改革）、江南开发",
            "隋唐时期：科举制创立、三省六部制、贞观之治、开元盛世、唐诗繁荣",
            "宋元时期：经济重心南移完成、活字印刷术、指南针、火药发明传播、行省制度、宋词元曲",
            "明清时期：君主专制强化（废丞相设内阁、军机处）、资本主义萌芽、郑和下西洋、闭关锁国、明清小说",
        ],
        "formulas": [
            "中国古代朝代顺序：夏→商→西周→东周（春秋→战国）→秦→西汉→东汉→三国→西晋→东晋十六国→南北朝→隋→唐→五代十国→北宋南宋→元→明→清",
            "中央集权制度演变：秦（皇帝制+三公九卿+郡县制）→汉（中外朝+推恩令）→隋唐（三省六部制）→宋（二府三司）→元（行省制）→明（废丞相设内阁）→清（军机处）",
            "选官制度演变：世卿世禄制（先秦）→军功爵制（秦）→察举制（汉）→九品中正制（魏晋）→科举制（隋唐至清）",
            "赋税制度演变：初税亩（春秋）→编户齐民（汉）→租庸调制（唐前期）→两税法（唐后期）→一条鞭法（明）→摊丁入亩（清）",
        ],
        "examples": [
            "例1：秦始皇巩固统一措施：政治上建立中央集权制度（皇帝制、三公九卿、郡县制）；经济上统一货币（圆形方孔钱）、度量衡；文化上统一文字（小篆）、焚书坑儒；军事上北击匈奴修长城、南征百越",
            "例2：汉武帝大一统措施：政治上颁布推恩令削弱诸侯王；思想上罢黜百家独尊儒术；经济上盐铁官营、统一铸五铢钱；军事上派卫青霍去病北击匈奴；外交上派张骞出使西域",
            "例3：科举制的影响：积极方面——打破世家大族垄断、扩大统治基础、提高官员素质、加强中央集权；消极方面——明清八股取士束缚思想、阻碍科技发展",
            "例4：唐朝盛世：贞观之治（唐太宗，轻徭薄赋、虚心纳谏、完善科举）→贞观遗风（武则天）→开元盛世（唐玄宗，唐朝全盛）",
            "例5：明清君主专制强化：明太祖废丞相权分六部，明成祖设内阁；雍正帝设军机处，君主专制达到顶峰",
        ],
        "methods": "中国古代史学习法：1.按时间顺序梳理朝代更替和重大事件（制作时间轴）；2.专题整理（政治制度演变、经济发展、文化成就、民族关系、对外交往）；3.理解重要制度的内容和影响（分封制、中央集权制、科举制等）；4.对比分析不同朝代的特点和联系；5.多做材料分析题，学会从材料中提取信息。",
        "common_mistakes": ["朝代顺序记错（特别是魏晋南北朝、五代十国等分裂时期）", "重要制度内容和影响混淆（分封制和郡县制、三省六部制和行省制）", "时间概念模糊（重大事件发生的朝代和时间记错）", "历史事件因果关系分析错误（只记事件不记背景和影响）", "对历史人物和事件评价片面（不能一分为二辩证分析）"],
    },
}

# ============================================================
# 地理知识点类别详情库
# ============================================================
_GEOGRAPHY_CATEGORY = {
    "自然地理": {
        "definition": "自然地理研究地球表层自然环境的组成、结构、功能、动态及其空间分异规律，包括地球运动、大气、水、地貌、土壤、植被、自然带等内容。",
        "key_points": [
            "地球运动：自转（自西向东，周期24小时，产生昼夜交替、地方时、地转偏向力）、公转（自西向东，周期1年，产生四季更替、五带划分、昼夜长短变化）",
            "大气：大气垂直分层（对流层、平流层、高层大气）、热力环流、气压带风带、天气系统（锋面、气旋反气旋）、气候类型",
            "水：水循环（海陆间循环、陆地内循环、海上内循环）、河流补给、洋流（风海流、密度流、补偿流，暖流增温增湿、寒流降温减湿）",
            "地貌：内力作用（地壳运动、岩浆活动、变质作用，形成褶皱、断层、火山）、外力作用（风化、侵蚀、搬运、沉积，形成流水地貌、风成地貌、冰川地貌、海岸地貌）",
            "自然带：由赤道到两极的地域分异（热量基础）、从沿海到内陆的地域分异（水分基础）、山地垂直地域分异（水热条件随海拔变化）",
        ],
        "formulas": [
            "地方时计算：所求地方时 = 已知地方时 ± 经度差 × 4分钟（东加西减）",
            "时区计算：所求区时 = 已知区时 ± 时区差（东加西减）",
            "正午太阳高度：H = 90° - |当地纬度 - 直射点纬度|",
            "昼夜长短：夏半年（直射北半球）北半球昼长夜短，纬度越高昼越长；冬半年相反",
            "气温垂直递减率：海拔每升高100米，气温下降约0.6℃",
            "洋流分布规律：中低纬度大洋环流（北顺南逆，东寒西暖）、中高纬度大洋环流（北逆南无，东暖西寒）、北印度洋季风洋流（夏顺冬逆）",
        ],
        "examples": [
            "例1：北京时间（东八区）12:00时，伦敦（中时区）时间=12-8=4:00，纽约（西五区）=12-13=前一天23:00",
            "例2：夏至日（太阳直射北回归线23.5°N），北京（40°N）正午太阳高度=90°-|40°-23.5°|=73.5°",
            "例3：热力环流：地面冷热不均→热空气上升（近地面低压）、冷空气下沉（近地面高压）→水平方向高压流向低压→形成环流",
            "例4：气候类型判断：以温定带（最冷月均温>15℃热带，0-15℃亚热带或温带海洋，<0℃温带），以水定型（年雨型、夏雨型、冬雨型、少雨型）",
            "例5：洋流对地理环境影响：暖流增温增湿（北大西洋暖流使西欧温带海洋性气候延伸到北极圈），寒流降温减湿（秘鲁寒流使沿岸形成沙漠），寒暖流交汇形成渔场（北海道、纽芬兰、北海渔场）",
        ],
        "methods": "自然地理学习法：1.理解基本原理（地球运动、大气运动、水循环、地质作用）；2.掌握规律和公式（地方时计算、正午太阳高度、气候类型判断、洋流分布）；3.多画图（地球运动图、大气环流图、洋流图、自然带分布图）；4.联系实际（用地理原理解释生活中的现象）；5.多做读图分析题，提高读图能力。",
        "common_mistakes": ["地方时和区时计算错误（东加西减方向搞反，时区差计算错误）", "正午太阳高度公式用错（纬度差计算错误）", "气压带风带分布和移动规律记错", "气候类型判断错误（气温和降水指标记错）", "洋流分布和性质记错（暖流寒流方向和位置混淆）", "内外力作用形成的地貌混淆（流水侵蚀和流水沉积地貌分不清）"],
    },
}

# ============================================================
# 政治知识点类别详情库
# ============================================================
_POLITICS_CATEGORY = {
    "经济生活": {
        "definition": "经济生活研究社会生产、分配、交换、消费等经济活动和经济关系，包括商品与货币、价格与消费、生产与经营、收入与分配、社会主义市场经济等内容。",
        "key_points": [
            "商品与货币：商品是用于交换的劳动产品，具有使用价值和价值两个基本属性；货币本质是一般等价物，职能有价值尺度、流通手段、贮藏手段、支付手段、世界货币",
            "价格：价值决定价格，供求影响价格；价值规律（商品价值量由社会必要劳动时间决定，商品交换以价值量为基础实行等价交换）；价格变动对生活和生产的影响",
            "消费：影响消费的因素（收入是基础和前提、物价、消费心理）；消费类型（钱货两清、贷款消费、租赁消费；生存资料、发展资料、享受资料）；正确消费观（量入为出适度消费、避免盲从理性消费、保护环境绿色消费、勤俭节约艰苦奋斗）",
            "生产与经营：生产决定消费，消费反作用于生产；我国基本经济制度（公有制为主体、多种所有制经济共同发展）；企业经营成功因素（正确经营战略、提高自主创新能力、诚信经营）",
            "收入与分配：按劳分配为主体、多种分配方式并存；效率与公平；财政收入与支出；税收的特征和作用",
            "社会主义市场经济：市场调节（自发性、盲目性、滞后性）、宏观调控（经济手段、法律手段、行政手段）、新发展理念、现代化经济体系",
        ],
        "formulas": [
            "商品价值量与社会必要劳动时间成正比，与社会劳动生产率成反比",
            "流通中所需货币量 = 商品价格总额 / 货币流通速度",
            "价值规律表现形式：价格围绕价值上下波动",
            "恩格尔系数 = 食品支出 / 家庭消费总支出 × 100%（系数越小生活水平越高）",
            "财政收入 = 税 + 利 + 债 + 其他收入",
            "个人所得税：超额累进税率，高收入者多纳税，低收入者少纳税",
        ],
        "examples": [
            "例1：商品价值量计算：如果生产一件衣服的社会必要劳动时间是2小时，价值100元；某企业提高劳动生产率1倍，2小时生产2件，每件价值仍为100元（价值量由社会必要劳动时间决定，与个别劳动生产率无关）",
            "例2：价格变动影响：猪肉价格上涨，消费者减少猪肉购买、增加鸡肉等替代品购买；生产者扩大生猪养殖规模",
            "例3：影响消费水平因素：居民收入是消费的基础和前提，当前可支配收入越多消费量越大；未来收入预期乐观则预支未来收入可能性大；收入差距过大则总体消费水平降低",
            "例4：企业经营成功因素：制定正确经营战略（如华为专注通信领域）；提高自主创新能力（依靠技术进步、科学管理形成竞争优势）；诚信经营树立良好信誉和形象（如海尔的售后服务）",
            "例5：宏观调控手段：经济手段（财政政策如税收、国债；货币政策如利率、存款准备金率）；法律手段（经济立法、经济司法）；行政手段（行政命令、指示、规定）",
        ],
        "methods": "经济生活学习法：1.理解基本概念（商品、货币、价值、价格、消费、生产、分配、市场经济）；2.掌握基本原理（价值规律、生产与消费关系、收入分配、市场调节与宏观调控）；3.联系经济热点（用经济学知识分析现实经济现象和政策）；4.掌握计算题方法（价值量、货币量、汇率、利率、税收计算）；5.构建知识体系（生产-分配-交换-消费四个环节的内在联系）。",
        "common_mistakes": ["商品价值量与劳动生产率关系混淆（社会劳动生产率和个别劳动生产率影响不同）", "货币职能判断错误（价值尺度和流通手段、支付手段混淆）", "影响消费的因素主次不分（收入是主要因素，物价是重要因素）", "公有制主体地位和国有经济主导作用混淆", "市场调节和宏观调控的关系理解错误（市场在资源配置中起决定性作用，宏观调控弥补市场不足）", "财政政策和货币政策混淆（财政政策与财政收支税收有关，货币政策与利率货币供应量有关）"],
    },
}

# ============================================================
# 通用其他学科生成函数
# ============================================================
def _generate_subject_detail(subject: str, chapter: str, point: str, category_dict: dict, category_map: list) -> dict:
    """通用学科知识点详情生成函数。"""
    # 匹配类别
    matched_category = None
    for keywords, cat_name in category_map:
        for kw in keywords:
            if kw in point or kw in chapter:
                matched_category = cat_name
                break
        if matched_category:
            break

    if matched_category and matched_category in category_dict:
        cat = category_dict[matched_category]
        definition = cat["definition"]
        if point not in definition:
            definition = f"【{point}】{definition}"
        return {
            "definition": definition,
            "key_points": cat["key_points"],
            "formulas": cat["formulas"],
            "examples": cat["examples"],
            "methods": cat["methods"],
            "common_mistakes": cat["common_mistakes"],
        }

    # 通用内容
    subject_name = {"physics": "物理", "chemistry": "化学", "biology": "生物",
                    "history": "历史", "geography": "地理", "politics": "政治",
                    "science": "科学", "morality": "道德与法治"}.get(subject, subject)

    definition = f"{point}是{subject_name}{chapter}部分的重要知识点，对于{subject_name}学习和理解具有重要意义。"

    key_points = [
        f"{point}的基本概念和定义",
        f"{point}的主要内容和基本原理",
        f"{point}的分类和类型",
        f"{point}与其他知识点的联系",
        f"{point}在实际生活中的应用",
    ]

    formulas = [
        f"{point}的基本原理和规律",
        f"应用{point}解决问题的方法和步骤",
    ]

    examples = [
        f"例1：{point}的基本概念理解题",
        f"例2：{point}的原理应用题",
        f"例3：{point}在实际生活中的应用",
    ]

    methods = f"学习{point}的方法：1.理解基本概念和原理；2.掌握相关规律和方法；3.通过例题学习应用；4.联系实际生活加深理解；5.多做练习巩固。学习时要注重理解，不要死记硬背，要学会用所学知识解释生活中的现象。"

    common_mistakes = [
        f"对{point}的概念理解不透彻",
        f"应用{point}的原理时忽略适用条件",
        f"与其他相关知识点混淆",
        f"不能联系实际生活灵活运用",
    ]

    return {
        "definition": definition,
        "key_points": key_points,
        "formulas": formulas,
        "examples": examples,
        "methods": methods,
        "common_mistakes": common_mistakes,
    }


# 各学科类别匹配映射
_PHYSICS_CATEGORY_MAP = [
    (["力学", "运动", "力", "牛顿", "功", "能", "动量", "振动", "波", "压强", "浮力", "机械"], "力学"),
    (["电磁", "电", "磁", "电场", "磁场", "电流", "电路", "电磁感应", "交流电"], "电磁学"),
    (["热学", "温度", "内能", "热量", "物态变化", "热力学"], "力学"),
    (["光学", "光", "反射", "折射", "透镜", "成像"], "力学"),
    (["原子", "核", "量子", "相对论"], "力学"),
]

_CHEMISTRY_CATEGORY_MAP = [
    (["物质结构", "原子", "分子", "元素", "周期", "化学键", "晶体", "电子排布"], "物质结构"),
    (["化学反应", "氧化还原", "离子反应", "反应速率", "化学平衡", "电解质", "pH", "电离", "水解"], "化学反应"),
    (["元素化合物", "金属", "非金属", "钠", "铝", "铁", "氯", "硫", "氮", "碳", "硅"], "物质结构"),
    (["有机化学", "烃", "醇", "醛", "酸", "酯", "苯", "同分异构"], "化学反应"),
    (["化学实验", "实验", "分离", "提纯", "检验", "配制"], "化学反应"),
]

_BIOLOGY_CATEGORY_MAP = [
    (["细胞", "分子", "蛋白质", "核酸", "细胞器", "细胞膜", "代谢", "光合", "呼吸", "分裂", "分化"], "细胞"),
    (["遗传", "DNA", "基因", "染色体", "减数分裂", "遗传规律", "变异", "进化"], "细胞"),
    (["稳态", "调节", "神经", "体液", "免疫", "内环境", "激素"], "细胞"),
    (["生态", "种群", "群落", "生态系统", "环境", "生物多样性"], "细胞"),
]

_HISTORY_CATEGORY_MAP = [
    (["中国古代", "先秦", "秦汉", "魏晋", "隋唐", "宋元", "明清", "古代史"], "中国古代史"),
    (["中国近代", "鸦片战争", "太平天国", "洋务", "戊戌", "辛亥", "五四", "抗战", "解放"], "中国古代史"),
    (["中国现代", "新中国", "社会主义", "改革开放", "现代化建设"], "中国古代史"),
    (["世界史", "古希腊", "罗马", "中世纪", "文艺复兴", "启蒙", "资产阶级革命", "工业革命", "两次世界大战", "冷战"], "中国古代史"),
]

_GEOGRAPHY_CATEGORY_MAP = [
    (["自然地理", "地球运动", "大气", "气候", "水", "洋流", "地貌", "地质", "自然带", "植被", "土壤"], "自然地理"),
    (["人文地理", "人口", "城市", "农业", "工业", "交通", "商业", "文化", "旅游"], "自然地理"),
    (["区域地理", "中国地理", "世界地理", "区域发展", "国土整治", "可持续发展"], "自然地理"),
]

_POLITICS_CATEGORY_MAP = [
    (["经济", "商品", "货币", "价格", "消费", "生产", "企业", "分配", "财政", "税收", "市场经济", "宏观调控"], "经济生活"),
    (["政治", "公民", "政府", "人大", "政党", "民族", "宗教", "国际", "外交", "民主", "法治"], "经济生活"),
    (["文化", "文化作用", "文化传承", "文化创新", "中华文化", "民族精神", "精神文明", "思想道德"], "经济生活"),
    (["哲学", "唯物论", "辩证法", "认识论", "历史唯物主义", "矛盾", "联系", "发展", "实践", "认识", "价值观"], "经济生活"),
]

