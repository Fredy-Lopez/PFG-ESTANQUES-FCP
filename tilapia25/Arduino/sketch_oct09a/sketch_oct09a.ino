#include <Wire.h>
#include <Adafruit_ADS1X15.h> 

// Crea el objeto para el ADS1115. Dirección por defecto 0x48.
Adafruit_ADS1115 ads; 

void setup(void) 
{
  // Iniciamos la comunicación serial a 115200 baudios.
  Serial.begin(115200); 
  
  // No imprimimos mensajes de inicio o error. Si hay un problema, 
  // el código simplemente se detendrá en la inicialización sin enviar nada.
  
  // Esperamos un momento para que el chip esté listo
  delay(100); 

  // Inicializa el ADS1115 y lo configura para FSR de +/-6.144V
  if (ads.begin()) {
    ads.setGain(GAIN_TWOTHIRDS); // Configura GAIN_TWOTHIRDS (+/-6.144V)
  }
  // Si ads.begin() falla, no hacemos nada y no enviamos nada al serial.
}

void loop(void) 
{
  int16_t adc0_raw;
  int16_t adc1_raw;

  // 1. Lectura del valor RAW del canal A0 (Single-Ended)
  adc0_raw = ads.readADC_SingleEnded(0);
  
  // 2. Lectura del valor RAW del canal A1 (Single-Ended)
  adc1_raw = ads.readADC_SingleEnded(1);
  
  // 3. Envío de datos al Monitor Serial (separados por coma)
  // Formato estricto: RAW_A0,RAW_A1\n
  
  Serial.print(adc0_raw); 
  Serial.print(",");
  // Usamos println para añadir el salto de línea y finalizar el registro
  Serial.println(adc1_raw); 

  // Pequeño retardo para controlar la tasa de muestreo
  delay(100); 
}
