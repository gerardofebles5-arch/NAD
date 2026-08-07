# Instalar Flutter SDK - Windows

Este documento guía la instalación de Flutter SDK para el desarrollo de Flutter Web.

## Paso 1: Descargar Flutter SDK

1. Ir a https://flutter.dev/docs/get-started/install/windows
2. Descargar la última versión estable de Flutter SDK (ZIP)
3. Guardar en un directorio accesible, ej: `C:\flutter`

## Paso 2: Extraer Flutter SDK

1. Extraer el archivo ZIP descargado
2. Mover la carpeta extraída a `C:\flutter`
3. La estructura final debe ser: `C:\flutter\bin\flutter.bat`

## Paso 3: Agregar Flutter al PATH

1. Buscar "Editar las variables de entorno del sistema" en Windows
2. Click en "Variables de entorno"
3. En "Variables del usuario", encontrar "Path"
4. Click en "Editar"
5. Click en "Nuevo"
6. Agregar: `C:\flutter\bin`
7. Click en "OK" en todas las ventanas

## Paso 4: Verificar Instalación

Cerrar y abrir una nueva terminal (PowerShell o CMD), luego ejecutar:

```bash
flutter --version
```

Debería mostrar la versión de Flutter instalada.

## Paso 5: Ejecutar Flutter Doctor

```bash
flutter doctor
```

Esto verificará las dependencias necesarias. Para Flutter Web, necesitas:

- ✅ Flutter SDK
- ✅ Android Studio / VS Code (opcional para Web)
- ✅ Chrome (para ejecutar Flutter Web)
- ✅ Git (para clonar proyectos)

## Paso 6: Habilitar Flutter Web

```bash
flutter config --enable-web
```

## Paso 7: Probar Flutter Web

```bash
cd C:\flutter
flutter create test_web
cd test_web
flutter run -d chrome
```

Esto debería abrir Chrome con una aplicación Flutter de prueba.

## Paso 8: Crear Proyecto NAD Scanner Flutter Web

Una vez instalado Flutter, navegar al directorio del proyecto:

```bash
cd "d:/nuevo escaner/nadscanner_final"
flutter create --platforms=web flutter_web
```

## Troubleshooting

**Error: "flutter no se reconoce"**
- Verifica que `C:\flutter\bin` esté en el PATH
- Cierra y abre una nueva terminal después de modificar el PATH

**Error: "No se encontró Chrome"**
- Instala Google Chrome
- Flutter necesita Chrome para ejecutar aplicaciones Web

**Error: "Git no encontrado"**
- Instala Git desde https://git-scm.com/download/win
- Agrega Git al PATH durante la instalación

## Siguiente Paso

Una vez instalado Flutter, continuar con Fase 5: Crear proyecto Flutter Web.
