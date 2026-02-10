/**
 * Initialize the SPI bus.
 *
 * :param speed_hz: Clock speed in Hz.
 * :returns: 0 on success.
 */
int spi_init(unsigned int speed_hz);

/**
 * Transfer data over SPI (full duplex).
 *
 * Sends and receives data simultaneously on the SPI bus.
 *
 * Example:
 *     uint8_t tx[] = {0x01, 0x02};
 *     uint8_t rx[2];
 *     spi_transfer(tx, rx, 2);
 *
 * For read-only transfers, pass NULL for tx:
 *
 * Example:
 *     uint8_t rx[4];
 *     spi_transfer(NULL, rx, 4);
 *
 * :param tx: Pointer to transmit buffer.
 * :param rx: Pointer to receive buffer.
 * :param len: Number of bytes.
 * :returns: 0 on success, negative on error.
 */
int spi_transfer(const void *tx, void *rx, int len);
