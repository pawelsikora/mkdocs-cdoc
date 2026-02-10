/**
 * Initialize the UART peripheral.
 *
 * :param baud: Baud rate (e.g. 115200).
 * :returns: 0 on success.
 */
int uart_init(unsigned int baud);

/**
 * Send a byte over UART.
 *
 * :param byte: The byte to transmit.
 */
void uart_send(unsigned char byte);

/**
 * Receive a byte from UART (blocking).
 *
 * :returns: The received byte.
 */
unsigned char uart_recv(void);
